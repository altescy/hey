import dataclasses
from collections.abc import Callable, Sequence

from .llm import LLMSpec
from .tool import AskPermissionFunc, ToolPermission, ToolSpec

type AgentResponseFormat[ResponseT] = type[ResponseT] | Callable[..., ResponseT]


@dataclasses.dataclass(frozen=True)
class LLMAgentSpec[QueryT, ResponseT]:
    llm: LLMSpec[QueryT]
    instructions: str
    response_format: AgentResponseFormat[ResponseT]
    tools: Sequence[ToolSpec] = ()
    permission: ToolPermission | None = None
    ask_permission: AskPermissionFunc | None = None
