import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from functools import partial
from typing import Any, TypeGuard, assert_never

from hey.core.workflow import BaseWorkflowHandler, Continue, Control, WorkflowNode
from hey.domain.entities.agent import LLMAgentSpec
from hey.domain.entities.llm import (
    LLMState,
    SystemMessage,
    TextContent,
)
from hey.domain.entities.tool import ToolSpec
from hey.domain.entities.workflow import (
    LLMWorkflowContext,
    LLMWorkflowContextEphemeral,
    LLMWorkflowEvent,
    LLMWorkflowNodeCompleted,
    LLMWorkflowState,
)
from hey.domain.services.agent import OnLLMEventCallback, make_tool_specs_for_agent, run_llm_agent
from hey.domain.services.tool import dump_tool_result_to_json, generate_tool_definition_from_spec

type PromptBuilder = Callable[[LLMWorkflowState], str]


def is_llm_workflow_event(event: LLMWorkflowEvent) -> TypeGuard[LLMWorkflowNodeCompleted[Any]]:
    return isinstance(event, LLMWorkflowNodeCompleted)


def make_llm_workflow_node_from_callable[ReturnT](
    func: Callable[[LLMWorkflowState], Awaitable[ReturnT]],
    *,
    name: str,
    deps: Sequence[str] = (),
    cond: Callable[["LLMWorkflowState"], bool] | None = None,
    until: Callable[["LLMWorkflowState"], bool] | None = None,
    context: LLMWorkflowContext | None = None,
) -> WorkflowNode[LLMWorkflowState, LLMWorkflowEvent, dict[str, Any]]:
    context = context or LLMWorkflowContextEphemeral(type="ephemeral")

    async def _wrapper(state: LLMWorkflowState) -> AsyncIterator[Control[LLMWorkflowEvent, dict[str, Any]]]:
        result = await func(state)
        yield Continue(
            LLMWorkflowNodeCompleted(
                node_name=name,
                context=context,
                state=state.contexts.get(name, LLMState()),
                result=result,
            )
        )

    return WorkflowNode(name=name, func=_wrapper, deps=deps, cond=cond, until=until)


def make_llm_workflow_node_from_agent[QueryT, ResponseT](
    spec: LLMAgentSpec[QueryT, ResponseT],
    *,
    name: str,
    prompt: str | PromptBuilder | None = None,
    deps: Sequence[str] = (),
    cond: Callable[["LLMWorkflowState"], bool] | None = None,
    until: Callable[["LLMWorkflowState"], bool] | None = None,
    context: LLMWorkflowContext | None = None,
    on_event: OnLLMEventCallback | None = None,
) -> WorkflowNode[LLMWorkflowState, LLMWorkflowEvent, dict[str, Any]]:

    prompt = prompt or partial(_default_prompt_builder, deps=deps)
    context = context or LLMWorkflowContextEphemeral(type="ephemeral")

    tool_specs, response_format_spec = make_tool_specs_for_agent(spec)

    async def _node_func(
        state: LLMWorkflowState,
        prompt: str | PromptBuilder,
    ) -> AsyncIterator[Control[LLMWorkflowEvent, dict[str, Any]]]:
        prompt = prompt(state) if callable(prompt) else prompt

        local_state = _resolve_local_state(
            state,
            context=context,
            instructions=spec.instructions,
            tools=tool_specs,
            finalizer=response_format_spec,
        )

        response = run_llm_agent(
            spec,
            prompt=prompt,
            state=local_state,
            on_event=on_event,
        )

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
        func=partial(_node_func, prompt=prompt),
        deps=deps,
        cond=cond,
        until=until,
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
            local_state = state.contexts.get(context["origin"], LLMState())
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
