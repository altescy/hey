import dataclasses
from typing import Literal


@dataclasses.dataclass(frozen=True, kw_only=True)
class BaseWorkflowProgressEvent[KindT: str]:
    kind: KindT
    total_nodes: int
    completed_nodes: int
    skipped_nodes: int

    @property
    def progress(self) -> float:
        if self.total_nodes == 0:
            return 1.0
        return (self.completed_nodes + self.skipped_nodes) / self.total_nodes


@dataclasses.dataclass(frozen=True, kw_only=True)
class WorkflowStartedEvent(BaseWorkflowProgressEvent[Literal["workflow_started"]]):
    kind: Literal["workflow_started"] = "workflow_started"


@dataclasses.dataclass(frozen=True, kw_only=True)
class WorkflowNodeStartedEvent(BaseWorkflowProgressEvent[Literal["node_started"]]):
    kind: Literal["node_started"] = "node_started"
    node_name: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class WorkflowNodeFinishedEvent(BaseWorkflowProgressEvent[Literal["node_finished"]]):
    kind: Literal["node_finished"] = "node_finished"
    node_name: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class WorkflowFinishedEvent(BaseWorkflowProgressEvent[Literal["workflow_finished"]]):
    kind: Literal["workflow_finished"] = "workflow_finished"


type WorkflowProgressEvent = (
    WorkflowStartedEvent | WorkflowNodeStartedEvent | WorkflowNodeFinishedEvent | WorkflowFinishedEvent
)
