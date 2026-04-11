import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, NewType

ToolName = NewType("ToolName", str)
type ParamPattern = str
type ToolPermissionAction = Literal["allow", "deny"]


type ToolParamPermission = Mapping[ParamPattern, ToolPermissionAction]
type ToolPermission = Mapping[ToolName, ToolParamPermission]


@dataclasses.dataclass(frozen=True, slots=True)
class ToolSpec[**ParamsT, ReturnT]:
    name: ToolName
    description: str
    func: Callable[ParamsT, Awaitable[ReturnT]]
    permission: ToolParamPermission
    parameters_annotation: type[dict[str, Any]]
    return_annotation: type[ReturnT]
