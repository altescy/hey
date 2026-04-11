import dataclasses
from collections.abc import AsyncIterator, Callable, Sequence
from typing import cast

from .controls import Continue, Control
from .graph import WorkflowGraph, WorkflowNode
from .handler import BaseWorkflowHandler


@dataclasses.dataclass(frozen=True)
class WorkflowLens[OuterStateT, InnerStateT]:
    get: Callable[[OuterStateT], InnerStateT]
    set: Callable[[OuterStateT, InnerStateT], OuterStateT]


@dataclasses.dataclass(frozen=True)
class WorkflowPrism[OuterEventT, InnerEventT]:
    inject: Callable[[InnerEventT], OuterEventT]
    try_get: Callable[[OuterEventT], InnerEventT | None]


class ComposedWorkflowHandler[
    OuterStateT,
    OuterEventT,
    OuterTerminalT,
    InnerStateT,
    InnerEventT,
    InnerTerminalT,
](BaseWorkflowHandler[OuterStateT, OuterEventT, OuterTerminalT]):
    def __init__(
        self,
        *,
        parent_handler: BaseWorkflowHandler[OuterStateT, OuterEventT, OuterTerminalT],
        child_handler: BaseWorkflowHandler[InnerStateT, InnerEventT, InnerTerminalT],
        state_lens: WorkflowLens[OuterStateT, InnerStateT],
        event_prism: WorkflowPrism[OuterEventT, InnerEventT],
    ) -> None:
        self._parent_handler = parent_handler
        self._child_handler = child_handler
        self._state_lens = state_lens
        self._event_prism = event_prism

    def update(self, events: Sequence[OuterEventT], state: OuterStateT) -> OuterStateT:
        current_state = state
        for event in events:
            child_event = self._event_prism.try_get(event)
            if child_event is None:
                current_state = self._parent_handler.update([event], current_state)
                continue

            child_state = self._state_lens.get(current_state)
            next_child_state = self._child_handler.update([child_event], child_state)
            current_state = self._state_lens.set(current_state, next_child_state)
        return current_state

    def finish(self, state: OuterStateT) -> OuterTerminalT:
        return self._parent_handler.finish(state)


def compose_mounts[
    ParentStateT,
    ParentEventT,
    ParentTerminalT,
](
    base_handler: BaseWorkflowHandler[ParentStateT, ParentEventT, ParentTerminalT],
    *composers: Callable[
        [BaseWorkflowHandler[ParentStateT, ParentEventT, ParentTerminalT]],
        BaseWorkflowHandler[ParentStateT, ParentEventT, ParentTerminalT],
    ],
) -> BaseWorkflowHandler[ParentStateT, ParentEventT, ParentTerminalT]:
    """複数のサブグラフ合成を順番に適用したハンドラを返す。"""

    handler = base_handler
    for compose in composers:
        handler = compose(handler)
    return handler


@dataclasses.dataclass(frozen=True)
class LiftedSubgraph:
    prefix: str
    done_node: str
    node_names: tuple[str, ...]


def _sink_node_names[
    StateT,
    EventT,
    TerminalT,
](graph: WorkflowGraph[StateT, EventT, TerminalT]) -> tuple[str, ...]:
    depended = {dep for node in graph.nodes for dep in node.deps}
    return tuple(node.name for node in graph.nodes if node.name not in depended)


def lift_subgraph_to_parent_graph[
    ParentStateT,
    ParentEventT,
    ParentTerminalT,
    ChildStateT,
    ChildEventT,
    ChildTerminalT,
](
    parent_graph: WorkflowGraph[ParentStateT, ParentEventT, ParentTerminalT],
    *,
    child_graph: WorkflowGraph[ChildStateT, ChildEventT, ChildTerminalT],
    state_lens: WorkflowLens[ParentStateT, ChildStateT],
    event_prism: WorkflowPrism[ParentEventT, ChildEventT],
    prefix: str,
    entry_deps: Sequence[str] = (),
    entry_cond: Callable[[ParentStateT], bool] | None = None,
) -> tuple[WorkflowGraph[ParentStateT, ParentEventT, ParentTerminalT], LiftedSubgraph]:
    graph = parent_graph
    node_names: list[str] = []

    for child_node in child_graph.nodes:
        lifted_name = f"{prefix}.{child_node.name}"

        async def lifted_func(
            parent_state: ParentStateT,
            _child_func: Callable[[ChildStateT], AsyncIterator[Control[ChildEventT, ChildTerminalT]]] = child_node.func,
        ) -> AsyncIterator[Control[ParentEventT, ParentTerminalT]]:
            child_state = state_lens.get(parent_state)
            async for control in _child_func(child_state):
                match control:
                    case Continue(event=event):
                        yield Continue(event_prism.inject(event))
                    case _:
                        raise RuntimeError("Stop from lifted subgraph node is not supported")

        if child_node.deps:
            lifted_deps = [f"{prefix}.{dep}" for dep in child_node.deps]
        else:
            lifted_deps = list(entry_deps)

        lifted_cond: Callable[[ParentStateT], bool] | None
        lifted_until: Callable[[ParentStateT], bool] | None

        if child_node.cond is None and entry_cond is None:
            lifted_cond = None
        elif child_node.cond is None:
            lifted_cond = entry_cond
        elif entry_cond is None:

            def _lifted_cond(
                state: ParentStateT,
                _child_cond: Callable[[ChildStateT], bool] = child_node.cond,
            ) -> bool:
                return _child_cond(state_lens.get(state))

            lifted_cond = _lifted_cond
        else:

            def _lifted_cond_with_entry(
                state: ParentStateT,
                _child_cond: Callable[[ChildStateT], bool] = child_node.cond,
                _entry_cond: Callable[[ParentStateT], bool] = entry_cond,
            ) -> bool:
                return _entry_cond(state) and _child_cond(state_lens.get(state))

            lifted_cond = _lifted_cond_with_entry

        if child_node.until is None:
            lifted_until = None
        else:

            def _lifted_until(
                state: ParentStateT,
                _child_until: Callable[[ChildStateT], bool] = child_node.until,
            ) -> bool:
                return _child_until(state_lens.get(state))

            lifted_until = _lifted_until

        graph = graph.add(
            WorkflowNode(
                name=lifted_name,
                func=lifted_func,
                deps=lifted_deps,
                cond=lifted_cond,
                until=lifted_until,
            )
        )
        node_names.append(lifted_name)

    sink_names = [f"{prefix}.{name}" for name in _sink_node_names(child_graph)]
    done_node = f"{prefix}.__done__"

    async def done(_state: ParentStateT) -> AsyncIterator[Control[ParentEventT, ParentTerminalT]]:
        if False:
            yield Continue(cast(ParentEventT, None))

    graph = graph.add(done_node, done, deps=sink_names)
    return graph, LiftedSubgraph(prefix=prefix, done_node=done_node, node_names=tuple(node_names))
