"""Tests for hey.core.schema.python (generate_function_signature)."""

from collections.abc import Awaitable, Coroutine
from typing import Any

import pytest

from hey.core.schema.python import FunctionSignature, generate_function_signature

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sync_add(a: int, b: int) -> int:
    """Sync function with two int params."""
    return a + b


async def _async_greet(name: str) -> str:
    """Async function returning str."""
    return f"Hello, {name}"


async def _returns_awaitable(x: float) -> Awaitable[bool]:
    """Returns an Awaitable; return annotation should be unwrapped to bool."""
    ...


async def _returns_coroutine(x: int) -> Coroutine[Any, Any, str]:
    """Returns a Coroutine; return annotation should be unwrapped to str."""
    ...


async def _no_return():  # type: ignore[return]
    """Function without return annotation."""
    pass


# ---------------------------------------------------------------------------
# TestGenerateFunctionSignature
# ---------------------------------------------------------------------------


class TestGenerateFunctionSignature:
    def test_returns_function_signature_named_tuple(self) -> None:
        sig = generate_function_signature(_sync_add)
        assert isinstance(sig, FunctionSignature)

    def test_name_matches_function_name(self) -> None:
        sig = generate_function_signature(_sync_add)
        assert sig.name == "_sync_add"

    def test_return_annotation_int(self) -> None:
        sig = generate_function_signature(_sync_add)
        assert sig.return_annotation is int

    def test_return_annotation_str_for_async(self) -> None:
        sig = generate_function_signature(_async_greet)
        assert sig.return_annotation is str

    def test_parameters_annotation_is_typed_dict(self) -> None:
        sig = generate_function_signature(_sync_add)
        # TypedDict creates a class; check that the field names match
        hints = sig.parameters_annotation.__annotations__
        assert set(hints.keys()) == {"a", "b"}
        assert hints["a"] is int
        assert hints["b"] is int

    def test_parameters_annotation_name_derived_from_function(self) -> None:
        sig = generate_function_signature(_sync_add)
        assert sig.parameters_annotation.__name__ == "_sync_add__parameters"

    def test_awaitable_return_is_unwrapped(self) -> None:
        sig = generate_function_signature(_returns_awaitable)
        assert sig.return_annotation is bool

    def test_coroutine_return_is_unwrapped(self) -> None:
        sig = generate_function_signature(_returns_coroutine)
        assert sig.return_annotation is str

    def test_raises_when_no_return_annotation(self) -> None:
        with pytest.raises(ValueError, match="must have a return annotation"):
            generate_function_signature(_no_return)

    def test_single_param_function(self) -> None:
        async def _single(x: float) -> float:
            return x

        sig = generate_function_signature(_single)
        assert sig.name == "_single"
        hints = sig.parameters_annotation.__annotations__
        assert set(hints.keys()) == {"x"}
        assert hints["x"] is float
        assert sig.return_annotation is float

    def test_no_param_function(self) -> None:
        def _zero() -> bool:
            return True

        sig = generate_function_signature(_zero)
        assert sig.name == "_zero"
        assert sig.parameters_annotation.__annotations__ == {}
        assert sig.return_annotation is bool

    def test_union_return_annotation_preserved(self) -> None:
        def _maybe(x: int) -> int | str:
            return x

        sig = generate_function_signature(_maybe)
        import typing

        args = typing.get_args(sig.return_annotation)
        assert set(args) == {int, str}
