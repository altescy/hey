"""Tests for hey.domain.services.llm."""

import asyncio
import json
from typing import Literal

import pytest

from hey.core.schema import generate_function_signature
from hey.domain.entities.llm import (
    AssistantMessage,
    EmitLLMMessage,
    LLMState,
    RunToolCall,
    TextContent,
    ToolCallRecord,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)
from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.exceptions.tool import ToolExecutionInterrupted
from hey.domain.services.llm import (
    append_user_message,
    finalize_llm,
    interpret_llm_cmds,
    is_llm_state_done,
    reduce_llm_signal,
    truncate,
    update_llm_state,
)

# ---------------------------------------------------------------------------
# Helpers shared across this module
# ---------------------------------------------------------------------------


def _user(text: str) -> UserMessage:
    return UserMessage(role="user", parts=(TextContent(type="text", text=text),))


def _assistant(text: str, tool_calls: tuple[ToolCallRecord, ...] = ()) -> AssistantMessage:
    return AssistantMessage(role="assistant", parts=(TextContent(type="text", text=text),), tool_calls=tool_calls)


def _tool_result(call_id: str, text: str) -> ToolResultMessage:
    return ToolResultMessage(role="tool_result", tool_call_id=call_id, parts=(TextContent(type="text", text=text),))


def _tool_call(name: str, args_json: str = "{}", call_id: str = "c1") -> ToolCallRecord:
    return ToolCallRecord(id=call_id, name=name, args_json=args_json)


def _tool_def(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description="", parameters={})


def _make_tool_spec(name: str, func=None, permission=None) -> ToolSpec:
    if func is None:

        async def _echo(text: str) -> str:
            return text

        func = _echo

    sig = generate_function_signature(func)
    return ToolSpec(
        name=ToolName(name),
        description="",
        func=func,
        permission=permission or {},
        parameters_annotation=sig.parameters_annotation,
        return_annotation=sig.return_annotation,
    )


# ---------------------------------------------------------------------------
# append_user_message
# ---------------------------------------------------------------------------


class TestAppendUserMessage:
    def test_adds_message_to_empty_history(self) -> None:
        state = LLMState()
        new_state = append_user_message(state, "hello")
        assert len(new_state.history) == 1
        assert new_state.history[0]["role"] == "user"

    def test_message_text_is_correct(self) -> None:
        state = LLMState()
        new_state = append_user_message(state, "hello world")
        assert new_state.history[0]["parts"][0]["text"] == "hello world"

    def test_appends_to_existing_history(self) -> None:
        state = LLMState(history=(_user("first"),))
        new_state = append_user_message(state, "second")
        assert len(new_state.history) == 2
        assert new_state.history[1]["parts"][0]["text"] == "second"

    def test_original_state_is_not_mutated(self) -> None:
        state = LLMState()
        append_user_message(state, "hello")
        assert len(state.history) == 0


# ---------------------------------------------------------------------------
# truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    @pytest.mark.parametrize(
        "text, max_bytes, direction, contains",
        [
            ("hello", 100, "tail", "hello"),
            ("hello world", 5, "tail", "[truncated ...]"),
            ("hello world", 5, "head", "[... truncated]"),
        ],
    )
    def test_truncation(self, text: str, max_bytes: int, direction: Literal["head", "tail"], contains: str) -> None:
        result = truncate(text, max_bytes, direction)
        assert contains in result

    def test_no_truncation_when_fits(self) -> None:
        text = "short"
        assert truncate(text, 1000) == text

    def test_multibyte_chars_not_split(self) -> None:
        # Japanese chars are 3 bytes each; truncating to 4 bytes must not split
        text = "あいう"
        result = truncate(text, 4, "tail")
        # result must be valid UTF-8 (no UnicodeDecodeError on encode/decode)
        result.encode("utf-8")
        assert "[truncated ...]" in result

    def test_tail_direction_keeps_start(self) -> None:
        text = "abcdefgh"
        result = truncate(text, 4, "tail")
        assert result.startswith("abcd")

    def test_head_direction_keeps_end(self) -> None:
        text = "abcdefgh"
        result = truncate(text, 4, "head")
        assert result.endswith("efgh")


# ---------------------------------------------------------------------------
# LLMAgentReducer
# ---------------------------------------------------------------------------


class TestLLMAgentReducer:
    def test_non_turn_done_emits_signal_and_accumulates(self) -> None:
        events, buffer = reduce_llm_signal(signal := {"type": "text_delta", "index": 0, "delta": "hi"}, None)
        assert len(events) == 1
        assert buffer.signals == (signal,)

    def test_turn_done_emits_assistant_message_and_resets_buffer(self) -> None:
        _, buf = reduce_llm_signal({"type": "text_part_done", "index": 0, "text": "hello"}, None)
        events, new_buf = reduce_llm_signal({"type": "turn_done", "reason": "stop", "usage": {}}, buf)
        assert len(events) == 1

        assert isinstance(events[0], EmitLLMMessage)
        msg = events[0].message
        assert msg["role"] == "assistant"
        assert msg["parts"][0]["text"] == "hello"
        assert new_buf.signals == ()

    def test_tool_call_part_done_is_included_in_turn(self) -> None:
        _, buf = reduce_llm_signal(
            {
                "type": "tool_call_part_done",
                "index": 0,
                "tool_call_id": "id1",
                "tool_name": "my_tool",
                "args_json": "{}",
            },
            None,
        )
        events, _ = reduce_llm_signal({"type": "turn_done", "reason": "stop", "usage": {}}, buf)

        assert isinstance(events[0], EmitLLMMessage)
        msg = events[0].message
        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["name"] == "my_tool"

    def test_none_buffer_is_treated_as_empty(self) -> None:
        _, buffer = reduce_llm_signal({"type": "text_delta", "index": 0, "delta": "x"}, None)
        assert len(buffer.signals) == 1


# ---------------------------------------------------------------------------
# LLMAgentUpdater
# ---------------------------------------------------------------------------


class TestLLMAgentUpdater:
    def test_assistant_message_added_to_history(self) -> None:
        state = LLMState(tools=(_tool_def("t"),))
        from hey.domain.entities.llm import EmitLLMMessage

        events = [EmitLLMMessage(_assistant("hi"))]
        new_state, cmds = update_llm_state(events, state)
        assert len(new_state.history) == 1
        assert new_state.history[0]["role"] == "assistant"
        assert cmds == []

    def test_tool_call_produces_run_command(self) -> None:
        tool = _tool_def("my_tool")
        state = LLMState(tools=(tool,))
        call = _tool_call("my_tool")
        from hey.domain.entities.llm import EmitLLMMessage

        events = [EmitLLMMessage(_assistant("", tool_calls=(call,)))]
        _, cmds = update_llm_state(events, state)
        assert len(cmds) == 1
        assert cmds[0].tool["name"] == "my_tool"

    def test_unknown_tool_call_produces_error_result(self) -> None:
        state = LLMState(tools=())
        call = _tool_call("nonexistent")
        from hey.domain.entities.llm import EmitLLMMessage

        events = [EmitLLMMessage(_assistant("", tool_calls=(call,)))]
        new_state, cmds = update_llm_state(events, state)
        assert cmds == []
        # history should include the assistant message + an error tool_result
        roles = [m["role"] for m in new_state.history]
        assert "tool_result" in roles

    def test_tool_result_event_added_to_history(self) -> None:
        state = LLMState()
        from hey.domain.entities.llm import EmitToolResult

        result_msg = _tool_result("c1", "ok")
        events = [EmitToolResult(message=result_msg, status="success")]
        new_state, _ = update_llm_state(events, state)
        assert new_state.history[-1]["role"] == "tool_result"


# ---------------------------------------------------------------------------
# LLMAgentFinalizer
# ---------------------------------------------------------------------------


class TestLLMAgentFinalizer:
    def test_not_done_when_history_empty(self) -> None:
        assert is_llm_state_done(LLMState()) is False

    def test_done_when_last_message_is_assistant(self) -> None:
        state = LLMState(history=(_user("hi"), _assistant("hello")))
        assert is_llm_state_done(state) is True

    def test_not_done_when_last_message_is_user(self) -> None:
        state = LLMState(history=(_assistant("hi"), _user("more")))
        assert is_llm_state_done(state) is False

    def test_finalize_returns_assistant_text(self) -> None:
        state = LLMState(history=(_assistant("final answer"),))
        result = finalize_llm(state)
        assert result == "final answer"

    def test_finalize_raises_when_not_done(self) -> None:
        with pytest.raises(RuntimeError):
            finalize_llm(LLMState())

    def test_done_with_finalizer_tool_when_tool_called(self) -> None:
        finalizer_def = _tool_def("finish")
        state = LLMState(
            finalizer=finalizer_def,
            history=(_assistant("", tool_calls=(_tool_call("finish", '{"answer":"42"}'),)),),
        )
        assert is_llm_state_done(state) is True

    def test_not_done_with_finalizer_tool_when_not_called(self) -> None:
        finalizer_def = _tool_def("finish")
        state = LLMState(finalizer=finalizer_def, history=(_assistant("hi"),))
        assert is_llm_state_done(state) is False


# ---------------------------------------------------------------------------
# LLMAgentInterpreter
# ---------------------------------------------------------------------------


class TestLLMAgentInterpreter:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_commands(self) -> None:
        result = await interpret_llm_cmds([], LLMState())
        assert result == []

    @pytest.mark.asyncio
    async def test_executes_tool_and_returns_result(self) -> None:
        async def _add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        tools = (_make_tool_spec("add", _add),)
        cmd = RunToolCall(
            record=_tool_call("add", json.dumps({"a": 1, "b": 2})),
            tool=_tool_def("add"),
        )
        results = await interpret_llm_cmds([cmd], LLMState(), tools=tools)
        assert len(results) == 1
        assert results[0].status == "success"
        assert "3" in results[0].message["parts"][0]["text"]

    @pytest.mark.asyncio
    async def test_tool_exception_yields_error_status(self) -> None:
        async def _bad(x: int) -> int:
            """Always fails."""
            raise ValueError("boom")

        tools = (_make_tool_spec("bad", _bad),)
        cmd = RunToolCall(record=_tool_call("bad", '{"x": 1}'), tool=_tool_def("bad"))
        results = await interpret_llm_cmds([cmd], LLMState(), tools=tools)
        assert results[0].status == "error"

    @pytest.mark.asyncio
    async def test_denied_permission_yields_denied_status(self) -> None:
        async def _secret(key: str) -> str:
            """Secret tool."""
            return key

        tools = (_make_tool_spec("secret", _secret, permission={"*": "deny"}),)
        cmd = RunToolCall(record=_tool_call("secret", '{"key": "x"}'), tool=_tool_def("secret"))
        results = await interpret_llm_cmds([cmd], LLMState(), tools=tools)
        assert results[0].status == "denied"

    @pytest.mark.asyncio
    async def test_multiple_tools_run_concurrently(self) -> None:
        import asyncio

        order: list[int] = []

        async def _slow(n: int) -> int:
            await asyncio.sleep(0.01)
            order.append(n)
            return n

        tools = (_make_tool_spec("slow", _slow),)
        cmds = [
            RunToolCall(record=_tool_call("slow", f'{{"n": {i}}}', call_id=f"c{i}"), tool=_tool_def("slow"))
            for i in range(3)
        ]
        results = await interpret_llm_cmds(cmds, LLMState(), tools=tools)
        assert len(results) == 3
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_eof_error_raises_with_fallback_tool_results(self) -> None:
        async def _interrupt(delay: float) -> str:
            if delay > 0:
                await asyncio.sleep(delay)
                return "done"
            raise EOFError()

        tools = (_make_tool_spec("interrupt", _interrupt),)
        cmds = [
            RunToolCall(record=_tool_call("interrupt", '{"delay": 0.1}', call_id="c1"), tool=_tool_def("interrupt")),
            RunToolCall(record=_tool_call("interrupt", '{"delay": 0}', call_id="c2"), tool=_tool_def("interrupt")),
        ]

        with pytest.raises(ToolExecutionInterrupted) as excinfo:
            await interpret_llm_cmds(cmds, LLMState(), tools=tools)

        exc = excinfo.value
        assert isinstance(exc.cause, EOFError)
        assert len(exc.events) == 2
        assert [event.message["tool_call_id"] for event in exc.events] == ["c1", "c2"]
        assert all(event.status == "error" for event in exc.events)
