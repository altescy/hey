import asyncio
import contextvars
import dataclasses
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any, Literal, TypeGuard, assert_never

from hey.core.agent import Reducer
from hey.core.pattern import json_match
from hey.domain.entities.llm import (
    AssistantMessage,
    ContentPart,
    EmitLLMMessage,
    EmitLLMSignal,
    EmitToolResult,
    LLMEvent,
    LLMMessage,
    LLMSignal,
    LLMState,
    TextContent,
    ToolCallRecord,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)
from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.exceptions.tool import ToolCallDenied
from hey.domain.services.tool import (
    construct_tool_parameters_from_json,
    construct_tool_result_from_json,
    dump_tool_result_to_json,
)

_LLM_STATE = contextvars.ContextVar[LLMState | None]("_LLM_STATE", default=None)
_MAX_TOOL_RESULT_BYTES = 50 * 1024  # 50 KB


def is_llm_event(obj: Any) -> TypeGuard[LLMEvent]:
    return isinstance(obj, (EmitLLMMessage, EmitLLMSignal, EmitToolResult))


def append_user_message(state: LLMState, text: str) -> LLMState:
    new_message = UserMessage(
        role="user",
        parts=(TextContent(type="text", text=text),),
    )
    return dataclasses.replace(state, history=state.history + (new_message,))


def truncate(s: str, max_bytes: int, direction: Literal["head", "tail"] = "tail") -> str:
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    match direction:
        case "head":
            truncated = encoded[-max_bytes:]
        case "tail":
            truncated = encoded[:max_bytes]
        case _:
            assert_never(direction)
    # Ensure we don't cut off in the middle of a multibyte character
    while True:
        try:
            output = truncated.decode("utf-8")
            match direction:
                case "head":
                    return "[... truncated]" + output
                case "tail":
                    return output + "[truncated ...]"
                case _:
                    assert_never(direction)

        except UnicodeDecodeError:
            if direction == "head":
                truncated = truncated[1:]
            else:
                truncated = truncated[:-1]


def use_llm_state() -> LLMState:
    state = _LLM_STATE.get()
    if state is None:
        raise RuntimeError("LLM state is not set in the current context")
    return state


@dataclasses.dataclass(frozen=True)
class RunToolCall:
    record: ToolCallRecord
    tool: ToolDefinition


@dataclasses.dataclass(frozen=True)
class LLMAgentBuffer:
    signals: tuple[LLMSignal, ...] = ()


class LLMAgentReducer(Reducer[LLMAgentBuffer, LLMSignal, LLMEvent]):
    def _compose_assistant_parts(self, buffer: Sequence[LLMSignal]) -> tuple[ContentPart, ...]:
        return tuple(
            TextContent(type="text", text=signal["text"]) for signal in buffer if signal["type"] == "text_part_done"
        )

    def _compose_assistant_tool_calls(self, buffer: Sequence[LLMSignal]) -> tuple[ToolCallRecord, ...]:
        return tuple(
            ToolCallRecord(id=signal["tool_call_id"], name=signal["tool_name"], args_json=signal["args_json"])
            for signal in buffer
            if signal["type"] == "tool_call_part_done"
        )

    def __call__(self, signal: LLMSignal, buffer: LLMAgentBuffer | None) -> tuple[Sequence[LLMEvent], LLMAgentBuffer]:
        buffer = buffer or LLMAgentBuffer()
        match signal["type"]:
            case "turn_done":
                return [
                    EmitLLMMessage(
                        AssistantMessage(
                            role="assistant",
                            parts=self._compose_assistant_parts(buffer.signals),
                            tool_calls=self._compose_assistant_tool_calls(buffer.signals),
                        )
                    ),
                ], LLMAgentBuffer()
            case _:
                return [EmitLLMSignal(signal)], dataclasses.replace(buffer, signals=buffer.signals + (signal,))


class LLMAgentUpdater:
    def __call__(
        self,
        events: Sequence[LLMEvent],
        state: LLMState,
    ) -> tuple[LLMState, Sequence[RunToolCall]]:
        tools: dict[str, ToolDefinition] = {tool["name"]: tool for tool in state.tools}
        if state.finalizer:
            tools[state.finalizer["name"]] = state.finalizer

        new_messages: list[LLMMessage] = []
        pending_cmds: list[RunToolCall] = []

        for event in events:
            match event:
                case EmitLLMMessage(message=message):
                    new_messages.append(message)
                    if message["role"] == "assistant":
                        for record in message["tool_calls"]:
                            tooldef = tools.get(record["name"])
                            if tooldef is not None:
                                pending_cmds.append(RunToolCall(record=record, tool=tooldef))
                            else:
                                new_messages.append(
                                    ToolResultMessage(
                                        role="tool_result",
                                        tool_call_id=record["id"],
                                        parts=(
                                            TextContent(type="text", text=f"Error: unknown tool '{record['name']}'"),
                                        ),
                                    )
                                )
                case EmitToolResult(message=message):
                    new_messages.append(message)

        new_state = dataclasses.replace(state, history=state.history + tuple(new_messages))

        return new_state, pending_cmds


class LLMAgentInterpreter:
    def __init__(self, tool_specs: Mapping[ToolName, ToolSpec]) -> None:
        self._tool_specs = tool_specs

    async def __call__(self, cmds: Sequence[RunToolCall], state: LLMState) -> list[EmitToolResult]:
        if not cmds:
            return []

        async def _execute(cmd: RunToolCall) -> EmitToolResult:
            tool_name = ToolName(cmd.tool["name"])
            tool_spec = self._tool_specs[tool_name]
            args_json = cmd.record["args_json"]
            status: Literal["success", "error", "denied"]
            output: str
            markdown: str | None = None

            permission_action = next(
                (
                    action
                    for pattern, action in reversed(list(tool_spec.permission.items()))
                    if json_match(args_json, pattern)
                ),
                "allow",
            )

            try:
                if permission_action == "ask":
                    if tool_spec.ask_permission is None:
                        raise ToolCallDenied("tool call denied because permission is required but not configured")
                    permission_action = await tool_spec.ask_permission(cmd.record)
                if permission_action != "allow":
                    raise ToolCallDenied("tool call denied by permission")

                params = construct_tool_parameters_from_json(tool_spec, args_json)
                result = await tool_spec.func(**params)
                output = dump_tool_result_to_json(result)
                status = "success"
                with suppress(Exception):
                    markdown = await tool_spec.render_markdown(result, **params) if tool_spec.render_markdown else None
            except ToolCallDenied as exc:
                output = f"Error: tool call denied: {exc}"
                status = "denied"
            except (KeyboardInterrupt, EOFError):
                raise
            except Exception as exc:
                output = f"Error: tool '{cmd.record['name']}' execution failed: {exc}"
                status = "error"
            output = truncate(output, _MAX_TOOL_RESULT_BYTES)
            message = ToolResultMessage(
                role="tool_result",
                tool_call_id=cmd.record["id"],
                parts=(TextContent(type="text", text=output),),
            )
            return EmitToolResult(message=message, status=status, markdown=markdown)

        token = _LLM_STATE.set(state)

        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(_execute(cmd)) for cmd in cmds]
        finally:
            _LLM_STATE.reset(token)

        return [task.result() for task in tasks]


class LLMAgentFinalizer:
    def __init__(self, tool_specs: Mapping[ToolName, ToolSpec]) -> None:
        self._tool_specs = tool_specs

    def is_done(self, state: LLMState) -> bool:
        if not state.history:
            return False
        if not state.finalizer:
            return state.history[-1]["role"] == "assistant"
        return any(
            any(record["name"] == state.finalizer["name"] for record in message["tool_calls"])
            for message in state.history
            if message["role"] == "assistant"
        )

    def finalize(self, state: LLMState) -> Any:
        if not self.is_done(state):
            raise RuntimeError("agent is not finalized yet")

        if not state.finalizer:
            assert state.history[-1]["role"] == "assistant"
            return "".join(part["text"] for part in state.history[-1]["parts"])

        tool_calls = {
            record["id"]: record
            for message in state.history
            if message["role"] == "assistant"
            for record in message["tool_calls"]
        }
        try:
            final_message = next(
                message
                for message in reversed(state.history)
                if message["role"] == "tool_result"
                and message["tool_call_id"] in tool_calls
                and tool_calls[message["tool_call_id"]]["name"] == state.finalizer["name"]
            )
        except StopIteration:
            raise RuntimeError("final result is not available until the agent is finalized")

        result_json = "".join(part["text"] for part in final_message["parts"])
        finalizer_spec = self._tool_specs[ToolName(state.finalizer["name"])]
        return construct_tool_result_from_json(finalizer_spec, result_json)
