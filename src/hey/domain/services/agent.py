from collections.abc import Awaitable

from hey.core.workflow.response import WorkflowResponse
from hey.domain.entities.agent import AgentResponseFormat, LLMAgentSpec
from hey.domain.entities.llm import LLMEvent, LLMState
from hey.domain.entities.tool import ToolSpec
from hey.domain.services.llm import (
    OnLLMEventCallback,
    append_user_message,
    extend_tools,
    overload_finalizer,
    run_llm,
)
from hey.domain.services.tool import (
    generate_tool_definition_from_spec,
    generate_tool_spec_from_callable,
    setup_tool_permission,
)


def make_response_format_tool_spec(
    response_format: AgentResponseFormat,
    *,
    name: str = "__finalize__",
    description: str = "Please call this tool with the final response to finish your turn",
) -> ToolSpec | None:
    if response_format is str:
        return None

    async def _finalize(output):
        return output

    _finalize.__annotations__ = {"output": response_format, "return": Awaitable[response_format]}

    return generate_tool_spec_from_callable(_finalize, name=name, description=description)


def make_tool_specs_for_agent[QueryT, ResponseT](
    spec: LLMAgentSpec[QueryT, ResponseT],
) -> tuple[tuple[ToolSpec, ...], ToolSpec | None]:
    tool_specs = setup_tool_permission(spec.tools, spec.permission, spec.ask_permission)
    response_format_spec = make_response_format_tool_spec(spec.response_format)
    return tool_specs, response_format_spec


def run_llm_agent[QueryT, ResponseT](
    spec: LLMAgentSpec[QueryT, ResponseT],
    *,
    prompt: str | None = None,
    state: LLMState | None = None,
    on_event: OnLLMEventCallback | None = None,
) -> WorkflowResponse[LLMEvent, LLMState, ResponseT]:
    tool_specs, response_format_spec = make_tool_specs_for_agent(spec)
    tool_defs = tuple(generate_tool_definition_from_spec(ts) for ts in tool_specs)
    response_format_def = generate_tool_definition_from_spec(response_format_spec) if response_format_spec else None

    if state is None:
        state = LLMState(
            history=(),
            tools=tool_defs,
            finalizer=response_format_def,
        )
    else:
        state = extend_tools(state, tool_defs)
        if response_format_def:
            state = overload_finalizer(state, response_format_def)

    if prompt:
        state = append_user_message(state, prompt)

    return run_llm(
        spec=spec.llm,
        response_format=response_format_spec,
        state=state,
        tools=tool_specs,
        on_event=on_event,
    )
