"""Tests for hey.core.workflow.graph (WorkflowNode, WorkflowGraph)."""

import dataclasses
from collections.abc import AsyncIterator

import pytest

from hey.core.workflow.controls import Continue, Control
from hey.core.workflow.graph import WorkflowGraph, WorkflowNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop(_state: object) -> AsyncIterator[Control[str, str]]:
    if False:
        yield Continue("")


async def _emit(event: str):
    async def _run(_state: object) -> AsyncIterator[Control[str, str]]:
        yield Continue(event)

    return _run


def _emit_sync(event: str):
    async def _run(_state: object) -> AsyncIterator[Control[str, str]]:
        yield Continue(event)

    return _run


# ---------------------------------------------------------------------------
# TestWorkflowNode
# ---------------------------------------------------------------------------


class TestWorkflowNode:
    def test_hash_is_based_on_name(self) -> None:
        node_a = WorkflowNode(name="x", func=_noop)
        node_b = WorkflowNode(name="x", func=_noop)
        assert hash(node_a) == hash(node_b)

    def test_nodes_with_different_names_have_different_hashes(self) -> None:
        node_a = WorkflowNode(name="a", func=_noop)
        node_b = WorkflowNode(name="b", func=_noop)
        assert hash(node_a) != hash(node_b)

    def test_default_deps_is_empty(self) -> None:
        node = WorkflowNode(name="n", func=_noop)
        assert list(node.deps) == []

    def test_default_cond_is_none(self) -> None:
        node = WorkflowNode(name="n", func=_noop)
        assert node.cond is None

    def test_default_until_is_none(self) -> None:
        node = WorkflowNode(name="n", func=_noop)
        assert node.until is None


# ---------------------------------------------------------------------------
# TestWorkflowGraph
# ---------------------------------------------------------------------------


class TestWorkflowGraph:
    def test_empty_graph_has_no_nodes(self) -> None:
        graph = WorkflowGraph()
        assert graph.nodes == ()

    def test_add_node_object(self) -> None:
        node = WorkflowNode(name="a", func=_noop)
        graph = WorkflowGraph().add(node)
        assert len(graph.nodes) == 1
        assert graph.nodes[0].name == "a"

    def test_add_by_name_and_func(self) -> None:
        graph = WorkflowGraph().add("a", _noop)
        assert len(graph.nodes) == 1
        assert graph.nodes[0].name == "a"

    def test_add_via_keyword_name(self) -> None:
        graph = WorkflowGraph().add(name="a", func=_noop)
        assert len(graph.nodes) == 1
        assert graph.nodes[0].name == "a"

    def test_add_returns_new_graph(self) -> None:
        g1 = WorkflowGraph()
        g2 = g1.add("a", _noop)
        assert g1 is not g2
        assert len(g1.nodes) == 0
        assert len(g2.nodes) == 1

    def test_add_multiple_nodes(self) -> None:
        graph = WorkflowGraph().add("a", _noop).add("b", _noop).add("c", _noop)
        assert len(graph.nodes) == 3
        names = [n.name for n in graph.nodes]
        assert names == ["a", "b", "c"]

    def test_add_with_deps(self) -> None:
        graph = WorkflowGraph().add("a", _noop).add("b", _noop, deps=["a"])
        assert list(graph.nodes[1].deps) == ["a"]

    def test_add_with_cond(self) -> None:
        cond = lambda _: True  # noqa: E731
        graph = WorkflowGraph().add("a", _noop, cond=cond)
        assert graph.nodes[0].cond is cond

    def test_add_with_until(self) -> None:
        until = lambda _: True  # noqa: E731
        graph = WorkflowGraph().add("a", _noop, until=until)
        assert graph.nodes[0].until is until

    def test_getitem_by_name(self) -> None:
        graph = WorkflowGraph().add("a", _noop).add("b", _noop)
        assert graph["a"].name == "a"
        assert graph["b"].name == "b"

    def test_getitem_raises_for_unknown_name(self) -> None:
        graph = WorkflowGraph().add("a", _noop)
        with pytest.raises(KeyError):
            _ = graph["unknown"]

    def test_add_duplicate_name_raises(self) -> None:
        with pytest.raises(ValueError, match="already exists"):
            WorkflowGraph().add("a", _noop).add("a", _noop)

    def test_add_both_positional_and_keyword_name_raises(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            WorkflowGraph().add("a", _noop, name="b")  # type: ignore[call-overload]

    def test_add_without_name_or_node_raises(self) -> None:
        with pytest.raises(ValueError, match="name must be provided"):
            WorkflowGraph().add(None, _noop)  # type: ignore[arg-type]

    def test_add_without_func_raises(self) -> None:
        with pytest.raises(ValueError, match="func must be provided"):
            WorkflowGraph().add("a")  # type: ignore[call-overload]

    def test_add_unknown_kwargs_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown keyword arguments"):
            WorkflowGraph().add("a", _noop, bogus_kwarg=True)  # type: ignore[call-overload]

    def test_graph_is_immutable(self) -> None:
        graph = WorkflowGraph()
        with pytest.raises(dataclasses.FrozenInstanceError):
            graph.nodes = ()  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Subgraph embedding via add(..., graph=...)
    # ------------------------------------------------------------------

    def test_add_subgraph_lifts_nodes(self) -> None:
        child = WorkflowGraph().add("x", _noop).add("y", _noop, deps=["x"])
        parent = WorkflowGraph().add(
            "sub",
            graph=child,
            map_state=lambda s: s,
            inject_event=lambda e: e,
        )
        node_names = [n.name for n in parent.nodes]
        assert "sub.x" in node_names
        assert "sub.y" in node_names
        # sentinel done node
        assert "sub" in node_names

    def test_add_subgraph_requires_map_state(self) -> None:
        child = WorkflowGraph().add("x", _noop)
        with pytest.raises(ValueError, match="map_state is required"):
            WorkflowGraph().add(
                "sub",
                graph=child,
                inject_event=lambda e: e,
            )  # type: ignore[call-overload]

    def test_add_subgraph_requires_inject_event(self) -> None:
        child = WorkflowGraph().add("x", _noop)
        with pytest.raises(ValueError, match="inject_event is required"):
            WorkflowGraph().add(
                "sub",
                graph=child,
                map_state=lambda s: s,
            )  # type: ignore[call-overload]

    def test_add_subgraph_requires_name(self) -> None:
        child = WorkflowGraph().add("x", _noop)
        with pytest.raises(ValueError, match="name must be provided"):
            WorkflowGraph().add(
                graph=child,
                map_state=lambda s: s,
                inject_event=lambda e: e,
            )  # type: ignore[call-overload]

    def test_add_subgraph_rejects_func(self) -> None:
        child = WorkflowGraph().add("x", _noop)
        with pytest.raises(ValueError, match="func must not be provided"):
            WorkflowGraph().add(
                "sub",
                _noop,  # type: ignore[arg-type]
                graph=child,
                map_state=lambda s: s,
                inject_event=lambda e: e,
            )
