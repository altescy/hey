import asyncio
import contextvars
import dataclasses
from collections.abc import Sequence
from typing import Any

from hey.core.agent import Reducer
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
from hey.domain.repositories.tool import IToolRepository
from hey.domain.services.tool import (
    construct_tool_parameters_from_json,
    construct_tool_result_from_json,
    dump_tool_result_to_json,
)


def append_user_message(state: LLMState, text: str) -> LLMState:
    new_message = UserMessage(
        role="user",
        parts=(TextContent(type="text", text=text),),
    )
    return dataclasses.replace(state, history=state.history + (new_message,))


_LLM_STATE = contextvars.ContextVar[LLMState | None]("_LLM_STATE", default=None)


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
    def __init__(self, tool_repository: IToolRepository) -> None:
        self._tool_repository = tool_repository

    async def __call__(self, cmds: Sequence[RunToolCall], state: LLMState) -> list[EmitToolResult]:
        if not cmds:
            return []

        async def _execute(cmd: RunToolCall) -> EmitToolResult:
            tool_spec = self._tool_repository.get_spec_by_name(cmd.tool["name"])
            try:
                params = construct_tool_parameters_from_json(tool_spec, cmd.record["args_json"])
                result = await tool_spec.func(**params)
                message = ToolResultMessage(
                    role="tool_result",
                    tool_call_id=cmd.record["id"],
                    parts=(TextContent(type="text", text=dump_tool_result_to_json(result)),),
                )
            except Exception as exc:
                message = ToolResultMessage(
                    role="tool_result",
                    tool_call_id=cmd.record["id"],
                    parts=(TextContent(type="text", text=f"Error: tool '{cmd.record['name']}' failed: {exc}"),),
                )
            return EmitToolResult(message=message)

        token = _LLM_STATE.set(state)

        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(_execute(cmd)) for cmd in cmds]
        finally:
            _LLM_STATE.reset(token)

        return [task.result() for task in tasks]


class LLMAgentFinalizer:
    def __init__(self, tool_repository: IToolRepository) -> None:
        self._tool_repository = tool_repository

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
        finalizer_spec = self._tool_repository.get_spec_by_name(state.finalizer["name"])
        return construct_tool_result_from_json(finalizer_spec, result_json)
