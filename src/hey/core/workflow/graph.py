import dataclasses
from collections.abc import AsyncIterator, Callable, Sequence
from functools import cached_property
from typing import Self, cast, overload

from .controls import Continue, Control


@dataclasses.dataclass(frozen=True)
class WorkflowNode[StateT, EventT, TerminalT]:
    name: str
    func: Callable[[StateT], AsyncIterator[Control[EventT, TerminalT]]]
    deps: Sequence[str] = dataclasses.field(default_factory=list)
    cond: Callable[[StateT], bool] | None = None
    until: Callable[[StateT], bool] | None = None

    def __hash__(self) -> int:
        """ノード名をキーにハッシュ化する。

        Returns:
            ノード名に基づくハッシュ値。
        """

        return hash(self.name)


@dataclasses.dataclass(frozen=True)
class WorkflowGraph[StateT, EventT, TerminalT]:
    nodes: tuple[WorkflowNode[StateT, EventT, TerminalT], ...] = dataclasses.field(default_factory=tuple)

    @cached_property
    def _index(self) -> dict[str, int]:
        return {node.name: i for i, node in enumerate(self.nodes)}

    def __getitem__(self, name: str) -> WorkflowNode[StateT, EventT, TerminalT]:
        return self.nodes[self._index[name]]

    @overload
    def add(
        self,
        node_or_name: WorkflowNode[StateT, EventT, TerminalT],
        /,
    ) -> Self: ...

    @overload
    def add(
        self,
        node_or_name: str,
        /,
        func: Callable[[StateT], AsyncIterator[Control[EventT, TerminalT]]],
        *,
        deps: Sequence[str] = (),
        cond: Callable[[StateT], bool] = ...,
        until: Callable[[StateT], bool] = ...,
    ) -> Self: ...

    @overload
    def add(
        self,
        node_or_name: None = None,
        /,
        func: Callable[[StateT], AsyncIterator[Control[EventT, TerminalT]]] | None = None,
        *,
        name: str,
        deps: Sequence[str] = (),
        cond: Callable[[StateT], bool] = ...,
        until: Callable[[StateT], bool] = ...,
    ) -> Self: ...

    @overload
    def add[
        ChildStateT,
        ChildEventT,
        ChildTerminalT,
    ](
        self,
        node_or_name: str,
        /,
        func: None = None,
        *,
        graph: "WorkflowGraph[ChildStateT, ChildEventT, ChildTerminalT]",
        map_state: Callable[[StateT], ChildStateT],
        inject_event: Callable[[ChildEventT], EventT],
        deps: Sequence[str] = (),
        cond: Callable[[StateT], bool] | None = None,
        until: Callable[[StateT], bool] = ...,
    ) -> Self: ...

    def add(
        self,
        node_or_name: WorkflowNode[StateT, EventT, TerminalT] | str | None = None,
        /,
        func: Callable[[StateT], AsyncIterator[Control[EventT, TerminalT]]] | None = None,
        **kwargs: object,
    ) -> Self:
        name = cast(str | None, kwargs.pop("name", None))
        graph = cast(WorkflowGraph[object, object, object] | None, kwargs.pop("graph", None))
        map_state = cast(Callable[[StateT], object] | None, kwargs.pop("map_state", None))
        inject_event = cast(Callable[[object], EventT] | None, kwargs.pop("inject_event", None))
        deps = cast(Sequence[str], kwargs.pop("deps", ()))
        cond = cast(Callable[[StateT], bool] | None, kwargs.pop("cond", (lambda _: True)))
        until = cast(Callable[[StateT], bool], kwargs.pop("until", (lambda _: True)))

        if kwargs:
            unknown_keys = ", ".join(sorted(kwargs.keys()))
            raise ValueError(f"Unknown keyword arguments: {unknown_keys}")

        if name is not None:
            if node_or_name is not None:
                raise ValueError("Specify either positional name/node or keyword 'name', not both")
            node_or_name = name

        if graph is not None:
            if isinstance(node_or_name, WorkflowNode):
                raise ValueError("node_or_name cannot be WorkflowNode when graph is provided")
            subgraph_name = node_or_name
            if subgraph_name is None:
                raise ValueError("name must be provided when adding a subgraph")
            if func is not None:
                raise ValueError("func must not be provided when adding a subgraph")
            if map_state is None:
                raise ValueError("map_state is required when adding a subgraph")
            if inject_event is None:
                raise ValueError("inject_event is required when adding a subgraph")

            if subgraph_name in self._index:
                raise ValueError(f"node with name '{subgraph_name}' already exists")

            current: WorkflowGraph[StateT, EventT, TerminalT] = self

            for child_node in graph.nodes:
                lifted_name = f"{subgraph_name}.{child_node.name}"

                if lifted_name in current._index:
                    raise ValueError(f"node with name '{lifted_name}' already exists")

                async def lifted_func(
                    state: StateT,
                    _child_func: Callable[[object], AsyncIterator[Control[object, object]]] = child_node.func,
                    _map_state: Callable[[StateT], object] = map_state,
                    _inject_event: Callable[[object], EventT] = inject_event,
                ) -> AsyncIterator[Control[EventT, TerminalT]]:
                    child_state = _map_state(state)
                    async for control in _child_func(child_state):
                        match control:
                            case Continue(event=event):
                                yield Continue(_inject_event(event))
                            case _:
                                raise RuntimeError("Stop from subgraph node is not supported")

                if child_node.deps:
                    lifted_deps = [f"{subgraph_name}.{dep}" for dep in child_node.deps]
                else:
                    lifted_deps = list(deps)

                child_cond = cast(Callable[[object], bool] | None, child_node.cond)
                lifted_cond: Callable[[StateT], bool] | None
                if child_cond is None and cond is None:
                    lifted_cond = None
                elif child_cond is None:
                    lifted_cond = cond
                elif cond is None:

                    def _lifted_cond(
                        state: StateT,
                        _child_cond: Callable[[object], bool] = child_cond,
                        _map_state: Callable[[StateT], object] = map_state,
                    ) -> bool:
                        return _child_cond(_map_state(state))

                    lifted_cond = _lifted_cond
                else:

                    def _lifted_cond_with_entry(
                        state: StateT,
                        _child_cond: Callable[[object], bool] = child_cond,
                        _entry_cond: Callable[[StateT], bool] = cond,
                        _map_state: Callable[[StateT], object] = map_state,
                    ) -> bool:
                        return _entry_cond(state) and _child_cond(_map_state(state))

                    lifted_cond = _lifted_cond_with_entry

                child_until = cast(Callable[[object], bool] | None, child_node.until)
                lifted_until: Callable[[StateT], bool] | None
                if child_until is None:
                    lifted_until = None
                else:

                    def _lifted_until(
                        state: StateT,
                        _child_until: Callable[[object], bool] = child_until,
                        _map_state: Callable[[StateT], object] = map_state,
                    ) -> bool:
                        return _child_until(_map_state(state))

                    lifted_until = _lifted_until

                current = current.add(
                    WorkflowNode(
                        name=lifted_name,
                        func=lifted_func,
                        deps=lifted_deps,
                        cond=lifted_cond,
                        until=lifted_until,
                    )
                )

            depended = {dep for node in graph.nodes for dep in node.deps}
            sink_names = [f"{subgraph_name}.{node.name}" for node in graph.nodes if node.name not in depended]

            async def done(_state: StateT) -> AsyncIterator[Control[EventT, TerminalT]]:
                if False:
                    yield Continue(cast(EventT, None))

            return current.add(subgraph_name, done, deps=sink_names)

        if isinstance(node_or_name, WorkflowNode):
            return dataclasses.replace(self, nodes=self.nodes + (node_or_name,))
        node_name = node_or_name
        if node_name is None:
            raise ValueError("name must be provided when adding a node with func")
        if func is None:
            raise ValueError("func must be provided when adding a node with name")
        if node_name in self._index:
            raise ValueError(f"node with name '{node_name}' already exists")
        return dataclasses.replace(self, nodes=self.nodes + (WorkflowNode(node_name, func, deps, cond, until),))
