import dataclasses
from collections.abc import AsyncIterator, Sequence

import pytest

from hey.core.workflow import (
    BaseWorkflowHandler,
    Continue,
    Control,
    WorkflowExecutor,
    WorkflowFinishedEvent,
    WorkflowGraph,
    WorkflowNodeStartedEvent,
)


@dataclasses.dataclass(frozen=True)
class _State:
    executed: tuple[str, ...] = ()


class _Handler(BaseWorkflowHandler[_State, str, tuple[str, ...]]):
    def update(self, events: Sequence[str], state: _State) -> _State:
        return dataclasses.replace(state, executed=state.executed + tuple(events))

    def finish(self, state: _State) -> tuple[str, ...]:
        return state.executed


def _node_event(event: str):
    async def _run(_: _State) -> AsyncIterator[Control[str, tuple[str, ...]]]:
        yield Continue(event)

    return _run


@pytest.mark.asyncio
async def test_executor_skips_node_by_cond_and_continues_dependents() -> None:
    def _skip(_: _State) -> bool:
        return False

    graph = (
        WorkflowGraph[_State, str, tuple[str, ...]]()
        .add(name="a", func=_node_event("a"))
        .add(name="b", func=_node_event("b"), cond=_skip)
        .add(name="c", func=_node_event("c"), deps=["a", "b"])
    )

    executor = WorkflowExecutor[_State, str, tuple[str, ...]](_Handler())
    response = await executor(graph, _State())

    events = [event async for event in response.events()]
    final_state, result = await response.collect()

    assert final_state.executed == ("a", "c")
    assert result == ("a", "c")

    node_start_names = [event.node_name for event in events if isinstance(event, WorkflowNodeStartedEvent)]
    assert node_start_names == ["a", "c"]

    finish_events = [event for event in events if isinstance(event, WorkflowFinishedEvent)]
    assert len(finish_events) == 1
    finish_event = finish_events[0]
    assert finish_event.completed_nodes == 2
    assert finish_event.skipped_nodes == 1
