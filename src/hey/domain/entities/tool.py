import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Concatenate, Literal, NewType

from hey.core.schema import JsonValue

from .llm import ToolCallRecord

ToolName = NewType("ToolName", str)
type ParamPattern = str
type ArgsJson = str
type ToolPermissionAction = Literal["allow", "deny", "ask"]


type ToolParamPermission = Mapping[ParamPattern, ToolPermissionAction]
type ToolPermission = Mapping[ToolName, ToolParamPermission]

type AskPermissionFunc = Callable[[ToolCallRecord], Awaitable[Literal["allow", "deny"]]]
type ToolRenderFunc[**ParamsT, ReturnT, ViewT] = Callable[Concatenate[ReturnT, ParamsT], Awaitable[ViewT]]


@dataclasses.dataclass(frozen=True, slots=True)
class ToolSpec[**ParamsT, ReturnT, ViewT]:
    name: ToolName
    description: str
    func: Callable[ParamsT, Awaitable[ReturnT]]
    permission: ToolParamPermission
    parameters_annotation: type[dict[str, Any]]
    return_annotation: type[ReturnT]
    parameters_schema: Mapping[str, JsonValue] | None = None
    render: ToolRenderFunc[ParamsT, ReturnT, ViewT] | None = None
    ask_permission: AskPermissionFunc | None = None
