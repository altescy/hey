import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from functools import partial
from typing import Any, TypeGuard, assert_never

from hey.core.agent import Reducer, make_agent_runtime, run_agent_loop
from hey.core.workflow import BaseWorkflowHandler, Continue, Control, WorkflowNode, WorkflowResponse
from hey.domain.entities.chat import ChatSessionID
from hey.domain.entities.llm import (
    EmitLLMMessage,
    EmitToolResult,
    LLMEvent,
    LLMMessage,
    LLMSignal,
    LLMSpec,
    LLMState,
    SystemMessage,
    TextContent,
    UserMessage,
)
from hey.domain.entities.tool import AskPermissionFunc, ToolPermission, ToolSpec
from hey.domain.entities.workflow import (
    LLMWorkflowContext,
    LLMWorkflowContextEphemeral,
    LLMWorkflowEvent,
    LLMWorkflowNodeCompleted,
    LLMWorkflowState,
)
from hey.domain.repositories.chat import IChatRepository
from hey.domain.services.llm import (
    LLMAgentFinalizer,
    LLMAgentInterpreter,
    LLMAgentReducer,
    LLMAgentUpdater,
)
from hey.domain.services.tool import (
    dump_tool_result_to_json,
    generate_tool_definition_from_spec,
    generate_tool_spec_from_callable,
    setup_tool_permission,
)

type PromptBuilder = Callable[[LLMWorkflowState], str]
type OnEventCallback[EventT] = Callable[[EventT], Awaitable[None]]


def is_llm_workflow_event(event: LLMWorkflowEvent) -> TypeGuard[LLMWorkflowNodeCompleted[Any]]:
    return isinstance(event, LLMWorkflowNodeCompleted)


def create_on_event_callback_for_chat(
    session_id: ChatSessionID,
    repository: IChatRepository,
) -> OnEventCallback[LLMEvent]:
    async def on_event(event: LLMEvent) -> None:
        match event:
            case EmitLLMMessage(message=message) | EmitToolResult(message=message):
                repository.create_message(session_id=session_id, message=message)

    return on_event


class LLMAgent[QueryT, ResponseT]:
    def __init__(
        self,
        spec: LLMSpec[QueryT],
        instructions: str,
        response_format: type[ResponseT] | Callable[..., ResponseT],
        tools: Sequence[ToolSpec] = (),
        permission: ToolPermission | None = None,
        ask_permission: AskPermissionFunc | None = None,
        reducer: Reducer[Any, LLMSignal, LLMEvent] | None = None,
    ) -> None:
        self._instructions = instructions
        self._engine = spec.engine
        self._contextualizer = spec.contextualizer
        self._response_format = response_format

        self._tools = setup_tool_permission(tools, permission, ask_permission)
        self._formatter = _build_finalizer_spec(response_format)

        tool_specs = {spec.name: spec for spec in self._tools}
        if self._formatter:
            tool_specs[self._formatter.name] = self._formatter

        self._reducer = reducer or LLMAgentReducer()
        self._updater = LLMAgentUpdater()
        self._interpreter = LLMAgentInterpreter(tool_specs)
        self._finalizer = LLMAgentFinalizer(tool_specs)

    def make_state(self, history: tuple[LLMMessage, ...] = ()) -> LLMState:
        tools = tuple(map(generate_tool_definition_from_spec, self._tools))
        finaliezr = generate_tool_definition_from_spec(self._formatter) if self._formatter else None
        return LLMState(history=history, tools=tools, finalizer=finaliezr)

    def as_node(
        self,
        name: str,
        prompt: str | PromptBuilder | None = None,
        *,
        deps: Sequence[str] = (),
        cond: Callable[["LLMWorkflowState"], bool] | None = None,
        context: LLMWorkflowContext | None = None,
    ) -> WorkflowNode[LLMWorkflowState, LLMWorkflowEvent, dict[str, Any]]:

        prompt = prompt or partial(_default_prompt_builder, deps=deps)
        context = context or LLMWorkflowContextEphemeral(type="ephemeral")

        async def _node_func(state: LLMWorkflowState) -> AsyncIterator[Control[LLMWorkflowEvent, dict[str, Any]]]:
            nonlocal prompt

            prompt = prompt(state) if callable(prompt) else prompt

            local_state = _resolve_local_state(
                state,
                context=context,
                instructions=self._instructions,
                tools=self._tools,
                finalizer=self._formatter,
            )

            response = self.run(prompt, state=local_state)

            async for event in response.events():
                yield Continue(event)

            next_local_state, result = await response.collect()

            yield Continue(
                LLMWorkflowNodeCompleted(
                    node_name=name,
                    context=context,
                    state=next_local_state,
                    result=result,
                )
            )

        return WorkflowNode(
            name=name,
            func=_node_func,
            deps=deps,
            cond=cond,
            until=lambda _: True,
        )

    def run(
        self,
        prompt: str | None = None,
        *,
        state: LLMState | None = None,
        on_event: OnEventCallback[LLMEvent] | None = None,
    ) -> WorkflowResponse[LLMEvent, LLMState, ResponseT]:
        state = state or self.make_state()
        if prompt:
            state = dataclasses.replace(
                state,
                history=state.history + (UserMessage(role="user", parts=(TextContent(type="text", text=prompt),)),),
            )
        runtime = make_agent_runtime(self._engine, self._reducer, self._contextualizer)
        return run_agent_loop(
            state,
            runtime=runtime,
            update=self._updater,
            interpret=self._interpreter,
            is_done=self._finalizer.is_done,
            finish=self._finalizer.finalize,
            on_event=on_event,
        )


class LLMWorkflowHandler(BaseWorkflowHandler[LLMWorkflowState, LLMWorkflowEvent, dict[str, Any]]):
    def update(self, events: Sequence[LLMWorkflowEvent], state: LLMWorkflowState) -> LLMWorkflowState:
        for event in events:
            match event:
                case LLMWorkflowNodeCompleted() as workflow_event:
                    match workflow_event.context["type"]:
                        case "new" | "continue":
                            state = dataclasses.replace(
                                state,
                                contexts={**state.contexts, workflow_event.context["context"]: event.state},
                            )
                        case "fork" if "context" in event.context:
                            state = dataclasses.replace(
                                state,
                                contexts={**state.contexts, event.context["context"]: event.state},
                            )
                    state = dataclasses.replace(
                        state,
                        artifacts={
                            **state.artifacts,
                            **{workflow_event.node_name: workflow_event.result},
                        },
                    )

        return state

    def finish(self, state: LLMWorkflowState) -> dict[str, Any]:
        return dict(state.artifacts)


def _build_finalizer_spec(response_format: type | Callable[..., Any]) -> ToolSpec | None:
    if response_format is str:
        return None

    async def _finalize(output):
        return output

    _finalize.__annotations__ = {"output": response_format, "return": Awaitable[response_format]}

    return generate_tool_spec_from_callable(
        _finalize,
        name="__finalize__",
        description="Please call this tool with the final response to finish your turn",
    )


def _resolve_local_state(
    state: LLMWorkflowState,
    *,
    context: LLMWorkflowContext,
    instructions: str,
    tools: Sequence[ToolSpec],
    finalizer: ToolSpec | None = None,
) -> LLMState:
    local_state: LLMState
    match context["type"]:
        case "ephemeral" | "new":
            local_state = LLMState()
        case "continue":
            local_state = state.contexts.get(context["context"], LLMState())
        case "fork":
            local_state = state.contexts.get(context["source"], LLMState())
        case _ as unknown:
            assert_never(unknown)

    local_state = dataclasses.replace(
        local_state,
        history=local_state.history
        + (SystemMessage(role="system", parts=(TextContent(type="text", text=instructions),)),),
        tools=tuple(map(generate_tool_definition_from_spec, tools)),
        finalizer=generate_tool_definition_from_spec(finalizer) if finalizer else None,
    )

    return local_state


def _default_prompt_builder(state: LLMWorkflowState, deps: Sequence[str]) -> str:
    artifacts = [state.artifacts[dep] for dep in deps if dep in state.artifacts]
    return dump_tool_result_to_json(artifacts)
