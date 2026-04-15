import dataclasses
from typing import Any, Literal, NotRequired, TypedDict

from hey.domain.entities.llm import LLMEvent, LLMState


class LLMWorkflowContextEphemeral(TypedDict):
    type: Literal["ephemeral"]


class LLMWorkflowContextNew(TypedDict):
    type: Literal["new"]
    context: str


class LLMWorkflowContextContinue(TypedDict):
    type: Literal["continue"]
    context: str


class LLMWorkflowContextFork(TypedDict):
    type: Literal["fork"]
    source: str
    context: NotRequired[str]


type LLMWorkflowContext = (
    LLMWorkflowContextEphemeral | LLMWorkflowContextNew | LLMWorkflowContextContinue | LLMWorkflowContextFork
)


@dataclasses.dataclass(frozen=True)
class LLMWorkflowState:
    contexts: dict[str, LLMState] = dataclasses.field(default_factory=dict)
    artifacts: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class LLMWorkflowNodeCompleted[ResultT]:
    node_name: str
    context: LLMWorkflowContext
    state: LLMState
    result: ResultT


type LLMWorkflowEvent[ResultT] = LLMWorkflowNodeCompleted[ResultT] | LLMEvent
