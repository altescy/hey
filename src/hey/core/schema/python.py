import inspect
import typing
from collections.abc import Awaitable, Callable, Coroutine
from types import UnionType
from typing import Any, NamedTuple, TypedDict, Union


def _reveal_annotation(schema: Any) -> Any:
    origin = typing.get_origin(schema)
    args = typing.get_args(schema)
    if origin in (Union, UnionType):
        return Union[tuple(_reveal_annotation(arg) for arg in args)]
    if origin in (Awaitable, Coroutine):
        return _reveal_annotation(args[-1])
    return schema


class FunctionSignature[ReturnT](NamedTuple):
    name: str
    parameters_annotation: type[dict[str, Any]]
    return_annotation: type[ReturnT]


def generate_function_signature[ReturnT](func: Callable[..., ReturnT], /) -> FunctionSignature[ReturnT]:
    sig = inspect.signature(func)
    if sig.return_annotation is inspect.Signature.empty:
        raise ValueError(f"Function {func} must have a return annotation")

    parameters_annotation = TypedDict(
        f"{func.__name__}__parameters",
        {name: param.annotation for name, param in sig.parameters.items()},  # pyright: ignore[reportGeneralTypeIssues],
    )
    return_annotation = _reveal_annotation(sig.return_annotation)
    return FunctionSignature(
        name=func.__name__,
        parameters_annotation=parameters_annotation,  # pyright: ignore[reportArgumentType],
        return_annotation=return_annotation,
    )
