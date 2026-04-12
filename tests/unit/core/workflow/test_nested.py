"""Tests for hey.core.workflow.nested (lift_subgraph_to_parent_graph, compose_mounts)."""

import dataclasses
from collections.abc import AsyncIterator, Sequence

from hey.core.workflow.controls import Continue, Control
from hey.core.workflow.graph import WorkflowGraph
from hey.core.workflow.handler import BaseWorkflowHandler
from hey.core.workflow.nested import (
    ComposedWorkflowHandler,
    WorkflowLens,
    WorkflowPrism,
    compose_mounts,
    lift_subgraph_to_parent_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Outer:
    outer_val: int = 0
    inner_val: int = 0


@dataclasses.dataclass(frozen=True)
class _Inner:
    inner_val: int = 0


# Outer events are tagged tuples: ("outer", ...) or ("inner", ...)
type _OuterEvent = tuple[str, str]
type _InnerEvent = str


def _outer_lens() -> WorkflowLens[_Outer, _Inner]:
    return WorkflowLens(
        get=lambda outer: _Inner(inner_val=outer.inner_val),
        set=lambda outer, inner: dataclasses.replace(outer, inner_val=inner.inner_val),
    )


def _outer_prism() -> WorkflowPrism[_OuterEvent, _InnerEvent]:
    return WorkflowPrism(
        inject=lambda inner_evt: ("inner", inner_evt),
        try_get=lambda outer_evt: outer_evt[1] if outer_evt[0] == "inner" else None,
    )


async def _noop(_state: object) -> AsyncIterator[Control[str, str]]:
    if False:
        yield Continue("")


async def _outer_noop(_state: _Outer) -> AsyncIterator[Control[_OuterEvent, str]]:
    if False:
        yield Continue(("", ""))


def _emit(event: str):
    async def _run(_state: object) -> AsyncIterator[Control[str, str]]:
        yield Continue(event)

    return _run


class _SimpleHandler(BaseWorkflowHandler[_Outer, _OuterEvent, list[str]]):
    def update(self, events: Sequence[_OuterEvent], state: _Outer) -> _Outer:
        return state

    def finish(self, state: _Outer) -> list[str]:
        return []


class _InnerHandler(BaseWorkflowHandler[_Inner, _InnerEvent, list[str]]):
    def update(self, events: Sequence[_InnerEvent], state: _Inner) -> _Inner:
        return state

    def finish(self, state: _Inner) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# TestWorkflowLens / TestWorkflowPrism
# ---------------------------------------------------------------------------


class TestWorkflowLens:
    def test_get_extracts_inner_state(self) -> None:
        lens = _outer_lens()
        outer = _Outer(outer_val=1, inner_val=42)
        inner = lens.get(outer)
        assert inner == _Inner(inner_val=42)

    def test_set_replaces_inner_state(self) -> None:
        lens = _outer_lens()
        outer = _Outer(outer_val=1, inner_val=0)
        new_outer = lens.set(outer, _Inner(inner_val=99))
        assert new_outer.inner_val == 99
        assert new_outer.outer_val == 1  # unchanged


class TestWorkflowPrism:
    def test_inject_wraps_inner_event(self) -> None:
        prism = _outer_prism()
        outer_evt = prism.inject("hello")
        assert outer_evt == ("inner", "hello")

    def test_try_get_returns_inner_event_for_matching(self) -> None:
        prism = _outer_prism()
        result = prism.try_get(("inner", "hello"))
        assert result == "hello"

    def test_try_get_returns_none_for_non_matching(self) -> None:
        prism = _outer_prism()
        result = prism.try_get(("outer", "something"))
        assert result is None


# ---------------------------------------------------------------------------
# TestComposedWorkflowHandler
# ---------------------------------------------------------------------------


class TestComposedWorkflowHandler:
    def _make_counting_parent(self):
        """Returns a handler that accumulates outer_val increments."""

        class _CountingParent(BaseWorkflowHandler[_Outer, _OuterEvent, int]):
            def update(self, events: Sequence[_OuterEvent], state: _Outer) -> _Outer:
                outer_only = [e for e in events if e[0] != "inner"]
                return dataclasses.replace(state, outer_val=state.outer_val + len(outer_only))

            def finish(self, state: _Outer) -> int:
                return state.outer_val

        return _CountingParent()

    def _make_counting_child(self):
        class _CountingChild(BaseWorkflowHandler[_Inner, _InnerEvent, int]):
            def update(self, events: Sequence[_InnerEvent], state: _Inner) -> _Inner:
                return dataclasses.replace(state, inner_val=state.inner_val + len(events))

            def finish(self, state: _Inner) -> int:
                return state.inner_val

        return _CountingChild()

    def test_outer_events_routed_to_parent(self) -> None:
        handler = ComposedWorkflowHandler(
            parent_handler=self._make_counting_parent(),
            child_handler=self._make_counting_child(),
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
        )
        state = _Outer()
        new_state = handler.update([("outer", "x"), ("outer", "y")], state)
        assert new_state.outer_val == 2
        assert new_state.inner_val == 0

    def test_inner_events_routed_to_child(self) -> None:
        handler = ComposedWorkflowHandler(
            parent_handler=self._make_counting_parent(),
            child_handler=self._make_counting_child(),
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
        )
        state = _Outer()
        new_state = handler.update([("inner", "a"), ("inner", "b"), ("inner", "c")], state)
        assert new_state.inner_val == 3
        assert new_state.outer_val == 0

    def test_finish_delegates_to_parent(self) -> None:
        handler = ComposedWorkflowHandler(
            parent_handler=self._make_counting_parent(),
            child_handler=self._make_counting_child(),
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
        )
        state = _Outer(outer_val=7)
        assert handler.finish(state) == 7


# ---------------------------------------------------------------------------
# TestComposeMounts
# ---------------------------------------------------------------------------


class TestComposeMounts:
    def test_no_composers_returns_base(self) -> None:
        base = _SimpleHandler()
        result = compose_mounts(base)
        assert result is base

    def test_single_composer_applied(self) -> None:
        base = _SimpleHandler()
        applied: list[BaseWorkflowHandler] = []

        def _composer(h):
            applied.append(h)
            return h

        compose_mounts(base, _composer)
        assert applied == [base]

    def test_multiple_composers_applied_in_order(self) -> None:
        base = _SimpleHandler()
        order: list[int] = []

        def _composer_factory(n: int):
            def _composer(h):
                order.append(n)
                return h

            return _composer

        compose_mounts(base, _composer_factory(1), _composer_factory(2), _composer_factory(3))
        assert order == [1, 2, 3]


# ---------------------------------------------------------------------------
# TestLiftSubgraphToParentGraph
# ---------------------------------------------------------------------------


class TestLiftSubgraphToParentGraph:
    def _make_simple_child(self) -> WorkflowGraph:
        """A child graph: a -> b."""

        async def _node_a(_: _Inner) -> AsyncIterator[Control[_InnerEvent, str]]:
            yield Continue("from_a")

        async def _node_b(_: _Inner) -> AsyncIterator[Control[_InnerEvent, str]]:
            yield Continue("from_b")

        return WorkflowGraph[_Inner, _InnerEvent, str]().add("a", _node_a).add("b", _node_b, deps=["a"])

    def test_lifted_node_names_are_prefixed(self) -> None:
        child = self._make_simple_child()
        parent = WorkflowGraph[_Outer, _OuterEvent, str]()
        new_parent, lifted = lift_subgraph_to_parent_graph(
            parent,
            child_graph=child,
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
            prefix="sub",
        )
        node_names = [n.name for n in new_parent.nodes]
        assert "sub.a" in node_names
        assert "sub.b" in node_names

    def test_done_node_added(self) -> None:
        child = self._make_simple_child()
        parent = WorkflowGraph[_Outer, _OuterEvent, str]()
        new_parent, lifted = lift_subgraph_to_parent_graph(
            parent,
            child_graph=child,
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
            prefix="sub",
        )
        assert lifted.done_node == "sub.__done__"
        node_names = [n.name for n in new_parent.nodes]
        assert "sub.__done__" in node_names

    def test_lifted_subgraph_metadata(self) -> None:
        child = self._make_simple_child()
        parent = WorkflowGraph[_Outer, _OuterEvent, str]()
        _, lifted = lift_subgraph_to_parent_graph(
            parent,
            child_graph=child,
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
            prefix="mypfx",
        )
        assert lifted.prefix == "mypfx"
        assert "mypfx.a" in lifted.node_names
        assert "mypfx.b" in lifted.node_names

    def test_done_node_depends_on_sink_nodes(self) -> None:
        child = self._make_simple_child()
        parent = WorkflowGraph[_Outer, _OuterEvent, str]()
        new_parent, lifted = lift_subgraph_to_parent_graph(
            parent,
            child_graph=child,
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
            prefix="sub",
        )
        done_node = new_parent[lifted.done_node]
        # "b" is the sink (not depended on by anyone), so done depends on sub.b
        assert "sub.b" in done_node.deps

    def test_entry_deps_propagated_to_entry_nodes(self) -> None:
        child = self._make_simple_child()
        parent = WorkflowGraph[_Outer, _OuterEvent, str]().add("gate", _outer_noop)
        new_parent, _ = lift_subgraph_to_parent_graph(
            parent,
            child_graph=child,
            state_lens=_outer_lens(),
            event_prism=_outer_prism(),
            prefix="sub",
            entry_deps=["gate"],
        )
        # "a" is an entry node (no child deps), so it should get entry_deps
        entry_node = new_parent["sub.a"]
        assert "gate" in entry_node.deps
