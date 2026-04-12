import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Concatenate, Literal, NewType

from .llm import ToolCallRecord

ToolName = NewType("ToolName", str)
type ParamPattern = str
type ArgsJson = str
type ToolPermissionAction = Literal["allow", "deny", "ask"]


type ToolParamPermission = Mapping[ParamPattern, ToolPermissionAction]
type ToolPermission = Mapping[ToolName, ToolParamPermission]

type AskPermissionFunc = Callable[[ToolCallRecord], Awaitable[Literal["allow", "deny"]]]
type RenderMarkdownFunc[**ParamsT, ReturnT] = Callable[Concatenate[ReturnT, ParamsT], Awaitable[str]]


@dataclasses.dataclass(frozen=True, slots=True)
class ToolSpec[**ParamsT, ReturnT]:
    name: ToolName
    description: str
    func: Callable[ParamsT, Awaitable[ReturnT]]
    permission: ToolParamPermission
    parameters_annotation: type[dict[str, Any]]
    return_annotation: type[ReturnT]
    render_markdown: RenderMarkdownFunc[ParamsT, ReturnT] | None = None
    ask_permission: AskPermissionFunc | None = None
