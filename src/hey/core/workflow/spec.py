import dataclasses

from .graph import WorkflowGraph
from .handler import BaseWorkflowHandler


@dataclasses.dataclass(frozen=True)
class WorkflowSpec[StateT, EventT, TerminalT]:
    graph: WorkflowGraph[StateT, EventT, TerminalT]
    handler: BaseWorkflowHandler[StateT, EventT, TerminalT]
    initial_state: StateT
