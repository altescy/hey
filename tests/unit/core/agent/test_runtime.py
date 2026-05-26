"""Tests for hey.core.agent.runtime (make_agent_runtime, run_agent_loop)."""

import dataclasses
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest

from hey.core.agent.runtime import InterpretInterrupted, make_agent_runtime, run_agent_loop

# ---------------------------------------------------------------------------
# Helpers for make_agent_runtime
# ---------------------------------------------------------------------------


def _make_engine(signals: list[str]):
    """Fake engine that yields the given signals synchronously."""

    @asynccontextmanager
    async def _engine(query: Any) -> AsyncIterator[AsyncIterable[str]]:
        async def _stream():
            for s in signals:
                yield s

        yield _stream()

    return _engine


def _make_reducer(mapping: dict[str, list[str]]):
    """Reducer that maps each signal to a list of events using ``mapping``."""

    def _reducer(signal: str, buffer: None) -> tuple[list[str], None]:
        return mapping.get(signal, []), None

    return _reducer


def _identity_contextualizer(state: Any) -> Any:
    return state


# ---------------------------------------------------------------------------
# TestMakeAgentRuntime
# ---------------------------------------------------------------------------


class TestMakeAgentRuntime:
    @pytest.mark.asyncio
    async def test_yields_events_from_engine(self) -> None:
        engine = _make_engine(["sig1", "sig2"])
        reducer = _make_reducer({"sig1": ["e1"], "sig2": ["e2", "e3"]})
        runtime = make_agent_runtime(engine, reducer, _identity_contextualizer)

        events = [e async for e in runtime("state")]
        assert events == ["e1", "e2", "e3"]

    @pytest.mark.asyncio
    async def test_empty_engine_yields_no_events(self) -> None:
        engine = _make_engine([])
        reducer = _make_reducer({})
        runtime = make_agent_runtime(engine, reducer, _identity_contextualizer)

        events = [e async for e in runtime("anything")]
        assert events == []

    @pytest.mark.asyncio
    async def test_reducer_with_no_matching_signal_yields_nothing(self) -> None:
        engine = _make_engine(["unknown"])
        reducer = _make_reducer({})  # no mapping -> empty list for every signal
        runtime = make_agent_runtime(engine, reducer, _identity_contextualizer)

        events = [e async for e in runtime("state")]
        assert events == []

    @pytest.mark.asyncio
    async def test_contextualizer_transforms_state_to_query(self) -> None:
        received_queries: list[str] = []

        @asynccontextmanager
        async def _capturing_engine(query: str) -> AsyncIterator[AsyncIterable[str]]:
            received_queries.append(query)

            async def _stream():
                yield "ok"

            yield _stream()

        def _reducer(signal: str, buffer: None) -> tuple[list[str], None]:
            return [signal], None

        def _contextualizer(state: int) -> str:
            return f"query:{state}"

        runtime = make_agent_runtime(_capturing_engine, _reducer, _contextualizer)
        _ = [e async for e in runtime(7)]
        assert received_queries == ["query:7"]


# ---------------------------------------------------------------------------
# Helpers for run_agent_loop
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _LoopState:
    count: int = 0
    done: bool = False


def _make_simple_runtime(events_per_call: list[str]):
    """Returns a runtime that yields the given events once, then nothing."""
    call_index = [0]

    async def _runtime(state: _LoopState) -> AsyncIterator[str]:
        idx = call_index[0]
        call_index[0] += 1
        if idx < len(events_per_call):
            yield events_per_call[idx]

    return _runtime


def _simple_update(events: Sequence[str], state: _LoopState) -> tuple[_LoopState, Sequence[str]]:
    new_count = state.count + len(events)
    done = new_count >= 2
    return dataclasses.replace(state, count=new_count, done=done), []


async def _no_interpret(cmds: Sequence[str], state: _LoopState) -> Sequence[str]:
    return []


# ---------------------------------------------------------------------------
# TestRunAgentLoop
# ---------------------------------------------------------------------------


class TestRunAgentLoop:
    @pytest.mark.asyncio
    async def test_loop_runs_until_done(self) -> None:
        state = _LoopState()

        # runtime emits "a" then "b"; after 2 events, done=True
        runtime = _make_simple_runtime(["a", "b"])

        response = run_agent_loop(
            state,
            runtime=runtime,
            update=_simple_update,
            interpret=_no_interpret,
            is_done=lambda s: s.done,
            finish=lambda s: s.count,
        )

        final_state, result = await response.collect()
        assert result == 2
        assert final_state.done is True

    @pytest.mark.asyncio
    async def test_events_are_published_to_stream(self) -> None:
        state = _LoopState()
        runtime = _make_simple_runtime(["x", "y"])

        response = run_agent_loop(
            state,
            runtime=runtime,
            update=_simple_update,
            interpret=_no_interpret,
            is_done=lambda s: s.done,
            finish=lambda s: s.count,
        )

        collected_events = [e async for e in response.events()]
        assert "x" in collected_events
        assert "y" in collected_events

    @pytest.mark.asyncio
    async def test_on_event_callback_called_for_each_event(self) -> None:
        state = _LoopState()
        runtime = _make_simple_runtime(["a", "b"])
        seen: list[str] = []

        async def _on_event(event: str) -> None:
            seen.append(event)

        response = run_agent_loop(
            state,
            runtime=runtime,
            update=_simple_update,
            interpret=_no_interpret,
            is_done=lambda s: s.done,
            finish=lambda s: s.count,
            on_event=_on_event,
        )
        await response.collect()
        assert seen == ["a", "b"]

    @pytest.mark.asyncio
    async def test_interpret_called_when_cmds_returned(self) -> None:
        state = _LoopState()
        interpreted: list[str] = []

        async def _runtime(s: _LoopState) -> AsyncIterator[str]:
            yield "trigger"

        def _update_with_cmd(events: Sequence[str], s: _LoopState) -> tuple[_LoopState, Sequence[str]]:
            if events == ["trigger"]:
                return dataclasses.replace(s, count=s.count + 1), ["cmd1"]
            # after cmd results come in, mark done
            return dataclasses.replace(s, count=s.count + 1, done=True), []

        async def _interpret(cmds: Sequence[str], s: _LoopState) -> Sequence[str]:
            interpreted.extend(cmds)
            return ["cmd_result"]

        response = run_agent_loop(
            state,
            runtime=_runtime,
            update=_update_with_cmd,
            interpret=_interpret,
            is_done=lambda s: s.done,
            finish=lambda s: s.count,
        )
        await response.collect()
        assert "cmd1" in interpreted

    @pytest.mark.asyncio
    async def test_finish_called_when_done(self) -> None:
        state = _LoopState(count=2, done=True)

        async def _empty_runtime(s: _LoopState) -> AsyncIterator[str]:
            return
            yield  # make it an async generator

        def _immediate_done(s: _LoopState) -> bool:
            return s.done

        response = run_agent_loop(
            state,
            runtime=_empty_runtime,
            update=lambda evts, s: (s, []),
            interpret=_no_interpret,
            is_done=_immediate_done,
            finish=lambda s: f"done:{s.count}",
        )
        _, result = await response.collect()
        assert result == "done:2"

    @pytest.mark.asyncio
    async def test_exception_propagated_from_runtime(self) -> None:
        state = _LoopState()

        async def _failing_runtime(s: _LoopState) -> AsyncIterator[str]:
            raise RuntimeError("boom")
            yield  # make it an async generator

        response = run_agent_loop(
            state,
            runtime=_failing_runtime,
            update=lambda evts, s: (s, []),
            interpret=_no_interpret,
            is_done=lambda s: False,
            finish=lambda s: None,
        )
        with pytest.raises(RuntimeError, match="boom"):
            await response.collect()

    @pytest.mark.asyncio
    async def test_tool_interruption_events_published_before_reraise(self) -> None:
        state = _LoopState()

        async def _runtime(s: _LoopState) -> AsyncIterator[str]:
            yield "trigger"

        def _update_with_cmd(events: Sequence[str], s: _LoopState) -> tuple[_LoopState, Sequence[str]]:
            if events == ["trigger"]:
                return dataclasses.replace(s, count=1), ["cmd1"]
            return dataclasses.replace(s, done=True), []

        interrupted_event = "tool_result_interrupted"

        async def _interrupting_interpret(cmds: Sequence[str], s: _LoopState) -> Sequence[str]:
            raise InterpretInterrupted(events=(interrupted_event,), cause=EOFError())

        seen: list[str] = []

        async def _on_event(event: str) -> None:
            seen.append(event)

        response = run_agent_loop(
            state,
            runtime=_runtime,
            update=_update_with_cmd,
            interpret=_interrupting_interpret,
            is_done=lambda s: s.done,
            finish=lambda s: s.count,
            on_event=_on_event,
        )

        with pytest.raises(EOFError):
            _ = [e async for e in response.events()]

        assert interrupted_event in seen
