import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any


@dataclasses.dataclass(frozen=True, slots=True)
class ToolSpec[**ParamsT, ReturnT]:
    name: str
    description: str
    func: Callable[ParamsT, Awaitable[ReturnT]]
    parameters_annotation: type[dict[str, Any]]
    return_annotation: type[ReturnT]
