import asyncio
import dataclasses
from collections import Counter, deque
from enum import Enum
from typing import assert_never

from .controls import Continue, Stop
from .events import (
    WorkflowFinishedEvent,
    WorkflowNodeFinishedEvent,
    WorkflowNodeStartedEvent,
    WorkflowProgressEvent,
    WorkflowStartedEvent,
)
from .graph import WorkflowGraph, WorkflowNode
from .handler import BaseWorkflowHandler
from .response import WorkflowResponse
from .source import EventSource


class _NodeStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclasses.dataclass
class _WorkflowExecution:
    total_nodes: int = 0
    completed_nodes: int = 0
    skipped_nodes: int = 0


class WorkflowExecutor[StateT, EventT, TerminalT]:
    def __init__(
        self,
        handler: BaseWorkflowHandler[StateT, EventT, TerminalT],
    ) -> None:
        self._handler = handler

    async def __call__(
        self,
        graph: WorkflowGraph[StateT, EventT, TerminalT],
        state: StateT,
    ) -> WorkflowResponse[WorkflowProgressEvent | EventT, StateT, TerminalT]:
        source = EventSource[WorkflowProgressEvent | EventT]()
        execution = _WorkflowExecution(total_nodes=len(graph.nodes))

        async def _ro() -> tuple[StateT, TerminalT]:
            try:
                return await self._run(graph, state, source, execution)
            except BaseException as exc:
                execution.skipped_nodes = max(0, execution.total_nodes - execution.completed_nodes)
                await source.publish(
                    WorkflowFinishedEvent(
                        total_nodes=execution.total_nodes,
                        completed_nodes=execution.completed_nodes,
                        skipped_nodes=execution.skipped_nodes,
                    )
                )
                await source.aclose(exception=exc)
                raise

        return WorkflowResponse(source, _ro)

    def _validate_graph(self, graph: WorkflowGraph[StateT, EventT, TerminalT]) -> None:
        if not graph.nodes:
            raise ValueError("workflow graph has no nodes")

        names = [node.name for node in graph.nodes]
        if len(names) != len(set(names)):
            duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
            raise ValueError(f"duplicate node names: {', '.join(duplicates)}")

        known = set(names)
        for node in graph.nodes:
            unknown = sorted(set(node.deps) - known)
            if unknown:
                raise ValueError(f"node '{node.name}' has unknown deps: {', '.join(unknown)}")

        indegree: dict[str, int] = {node.name: len(set(node.deps)) for node in graph.nodes}
        dependents: dict[str, list[str]] = {node.name: [] for node in graph.nodes}
        for node in graph.nodes:
            for dependency in set(node.deps):
                dependents[dependency].append(node.name)

        ready = deque(name for name in names if indegree[name] == 0)
        visited = 0
        while ready:
            current = ready.popleft()
            visited += 1
            for dependent in dependents[current]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)

        if visited != len(graph.nodes):
            raise ValueError("workflow graph has cyclic deps")

    async def _run(
        self,
        graph: WorkflowGraph[StateT, EventT, TerminalT],
        state: StateT,
        source: EventSource[WorkflowProgressEvent | EventT],
        execution: _WorkflowExecution,
    ) -> tuple[StateT, TerminalT]:
        self._validate_graph(graph)

        await source.publish(
            WorkflowStartedEvent(
                total_nodes=execution.total_nodes,
                completed_nodes=execution.completed_nodes,
                skipped_nodes=execution.skipped_nodes,
            )
        )

        node_by_name = {node.name: node for node in graph.nodes}
        indegree: dict[WorkflowNode, int] = {node: len(set(node.deps)) for node in graph.nodes}
        dependents: dict[WorkflowNode, list[WorkflowNode]] = {node: [] for node in graph.nodes}
        for node in graph.nodes:
            for dependency in set(node.deps):
                dependents[node_by_name[dependency]].append(node)

        order = {node: i for i, node in enumerate(graph.nodes)}
        ready: deque[WorkflowNode] = deque(node for node in graph.nodes if indegree[node] == 0)
        remaining = set(order)
        status: dict[WorkflowNode, _NodeStatus] = {node: _NodeStatus.PENDING for node in graph.nodes}
        current_state = state

        while ready:
            batch_nodes = list(ready)
            ready.clear()

            runnable_nodes: list[WorkflowNode[StateT, EventT, TerminalT]] = []
            for node in sorted(batch_nodes, key=lambda name: order[name]):
                if self._should_run_node(node, current_state):
                    status[node] = _NodeStatus.RUNNING
                    runnable_nodes.append(node)
                    await source.publish(
                        WorkflowNodeStartedEvent(
                            total_nodes=execution.total_nodes,
                            completed_nodes=execution.completed_nodes,
                            skipped_nodes=execution.skipped_nodes,
                            node_name=node.name,
                        )
                    )
                else:
                    status[node] = _NodeStatus.SKIPPED
                    execution.skipped_nodes += 1

            batch_results: list[
                tuple[WorkflowNode[StateT, EventT, TerminalT], list[EventT], Stop[TerminalT] | None]
            ] = []
            if runnable_nodes:
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(self._run_node(node, current_state, source)) for node in runnable_nodes]

                batch_results = [t.result() for t in tasks]

            stop: Stop[TerminalT] | None = None
            for node, events, maybe_stop in sorted(batch_results, key=lambda result: order[result[0]]):
                if events:
                    current_state = self._handler.update(events, current_state)
                if node.until is None or node.until(current_state):
                    status[node] = _NodeStatus.COMPLETED
                    execution.completed_nodes += 1
                    await source.publish(
                        WorkflowNodeFinishedEvent(
                            total_nodes=execution.total_nodes,
                            completed_nodes=execution.completed_nodes,
                            skipped_nodes=execution.skipped_nodes,
                            node_name=node.name,
                        )
                    )
                if stop is None and maybe_stop is not None:
                    stop = maybe_stop

            if stop is not None:
                remaining.difference_update(
                    node for node in remaining if status[node] in (_NodeStatus.COMPLETED, _NodeStatus.SKIPPED)
                )
                execution.skipped_nodes += len(remaining)
                await source.publish(
                    WorkflowFinishedEvent(
                        total_nodes=execution.total_nodes,
                        completed_nodes=execution.completed_nodes,
                        skipped_nodes=execution.skipped_nodes,
                    )
                )
                await source.aclose()
                return current_state, stop.result

            for node in batch_nodes:
                if status[node] in (_NodeStatus.COMPLETED, _NodeStatus.SKIPPED):
                    remaining.discard(node)
                    for dependent in dependents[node]:
                        indegree[dependent] -= 1
                        if indegree[dependent] == 0:
                            ready.append(dependent)
                else:
                    status[node] = _NodeStatus.PENDING
                    ready.append(node)

        if remaining:
            raise RuntimeError(
                f"workflow execution ended with unprocessed nodes: {', '.join(sorted(node.name for node in remaining))}"
            )

        terminal_result = self._handler.finish(current_state)
        await source.publish(
            WorkflowFinishedEvent(
                total_nodes=execution.total_nodes,
                completed_nodes=execution.completed_nodes,
                skipped_nodes=execution.skipped_nodes,
            )
        )
        await source.aclose()

        return current_state, terminal_result

    def _should_run_node(
        self,
        node: WorkflowNode[StateT, EventT, TerminalT],
        state: StateT,
    ) -> bool:
        if node.cond is None:
            return True

        return node.cond(state)

    async def _run_node(
        self,
        node: WorkflowNode[StateT, EventT, TerminalT],
        state: StateT,
        source: EventSource[WorkflowProgressEvent | EventT],
    ) -> tuple[WorkflowNode, list[EventT], Stop[TerminalT] | None]:
        events: list[EventT] = []
        stop: Stop[TerminalT] | None = None

        async for control in node.func(state):
            match control:
                case Continue(event=event):
                    await source.publish(event)
                    events.append(event)
                case Stop():
                    return node, events, control
                case _:
                    assert_never(control)

        return node, events, stop
