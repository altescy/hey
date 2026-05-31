"""Tests for hey.domain.services.tool."""

import json
from typing import Literal

import pytest

from hey.core.schema import generate_function_signature
from hey.domain.entities.tool import ToolName, ToolSpec
from hey.domain.services.tool import (
    construct_tool_parameters_from_json,
    construct_tool_result_from_json,
    dump_tool_result_to_json,
    generate_tool_definition_from_spec,
    generate_tool_spec_from_callable,
    override_tool_permission,
    set_ask_permission,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _echo(text: str) -> str:
    """Echo the input text."""
    return text


async def _add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


async def _no_return():  # type: ignore[return]
    pass


def _make_spec(func=_echo, name: str | None = None, permission=None) -> ToolSpec:
    sig = generate_function_signature(func)
    return ToolSpec(
        name=ToolName(name or func.__name__),
        description=func.__doc__ or "",
        func=func,
        permission=permission or {},
        parameters_annotation=sig.parameters_annotation,
        return_annotation=sig.return_annotation,
    )


# ---------------------------------------------------------------------------
# generate_tool_spec_from_callable
# ---------------------------------------------------------------------------


class TestGenerateToolSpecFromCallable:
    def test_uses_function_name_by_default(self) -> None:
        spec = generate_tool_spec_from_callable(_echo)
        assert spec.name == "_echo"

    def test_custom_name_overrides(self) -> None:
        spec = generate_tool_spec_from_callable(_echo, name="my_echo")
        assert spec.name == "my_echo"

    def test_uses_docstring_as_description(self) -> None:
        spec = generate_tool_spec_from_callable(_echo)
        assert "Echo" in spec.description

    def test_custom_description_overrides(self) -> None:
        spec = generate_tool_spec_from_callable(_echo, description="custom desc")
        assert spec.description == "custom desc"

    def test_parameters_annotation_has_correct_keys(self) -> None:
        spec = generate_tool_spec_from_callable(_add)
        import typing

        fields = typing.get_type_hints(spec.parameters_annotation)
        assert "a" in fields
        assert "b" in fields

    def test_raises_when_no_return_annotation(self) -> None:
        with pytest.raises(ValueError):
            generate_tool_spec_from_callable(_no_return)


# ---------------------------------------------------------------------------
# generate_tool_definition_from_spec
# ---------------------------------------------------------------------------


class TestGenerateToolDefinitionFromSpec:
    def test_name_matches_spec(self) -> None:
        spec = _make_spec(_echo)
        defn = generate_tool_definition_from_spec(spec)
        assert defn["name"] == spec.name

    def test_description_matches_spec(self) -> None:
        spec = _make_spec(_echo)
        defn = generate_tool_definition_from_spec(spec)
        assert defn["description"] == spec.description

    def test_parameters_is_mapping(self) -> None:
        spec = _make_spec(_add)
        defn = generate_tool_definition_from_spec(spec)
        assert isinstance(defn["parameters"], dict)


# ---------------------------------------------------------------------------
# override_tool_permission / set_ask_permission
# ---------------------------------------------------------------------------


class TestOverrideToolPermission:
    def test_replaces_permission(self) -> None:
        spec = _make_spec(permission={"*": "allow"})
        new_spec = override_tool_permission(spec, {"*": "deny"})
        assert new_spec.permission == {"*": "deny"}

    def test_original_spec_unchanged(self) -> None:
        spec = _make_spec(permission={"*": "allow"})
        override_tool_permission(spec, {"*": "deny"})
        assert spec.permission == {"*": "allow"}


class TestSetAskPermission:
    def test_sets_ask_permission_func(self) -> None:
        spec = _make_spec()
        assert spec.ask_permission is None

        async def _ask(record) -> Literal["allow", "deny"]:
            return "allow"

        new_spec = set_ask_permission(spec, _ask)
        assert new_spec.ask_permission is _ask

    def test_original_spec_unchanged(self) -> None:
        spec = _make_spec()

        async def _ask(record) -> Literal["allow", "deny"]:
            return "allow"

        set_ask_permission(spec, _ask)
        assert spec.ask_permission is None


# ---------------------------------------------------------------------------
# construct_tool_parameters_from_json
# ---------------------------------------------------------------------------


class TestConstructToolParametersFromJson:
    @pytest.mark.parametrize(
        "args_json, expected",
        [
            ('{"text": "hello"}', {"text": "hello"}),
            ('{"text": ""}', {"text": ""}),
        ],
    )
    def test_deserializes_string_param(self, args_json: str, expected: dict) -> None:
        spec = _make_spec(_echo)
        params = construct_tool_parameters_from_json(spec, args_json)
        assert params == expected

    def test_deserializes_int_params(self) -> None:
        spec = _make_spec(_add)
        params = construct_tool_parameters_from_json(spec, '{"a": 3, "b": 4}')
        assert params == {"a": 3, "b": 4}


# ---------------------------------------------------------------------------
# dump_tool_result_to_json / construct_tool_result_from_json
# ---------------------------------------------------------------------------


class TestDumpAndConstructToolResult:
    @pytest.mark.parametrize(
        "value",
        ["hello", "", 'with "quotes"'],
    )
    def test_roundtrip_string(self, value: str) -> None:
        # For str return type, construct_tool_result_from_json returns the raw
        # JSON-encoded string (not the decoded Python str). This is because the
        # LLM tool-call result is kept as JSON text when the annotation is str.
        dumped = dump_tool_result_to_json(value)
        spec = _make_spec(_echo)
        result = construct_tool_result_from_json(spec, dumped)
        assert result == dumped  # raw JSON string, e.g. '"hello"'

    def test_roundtrip_int(self) -> None:
        dumped = dump_tool_result_to_json(42)
        spec = _make_spec(_add)
        result = construct_tool_result_from_json(spec, dumped)
        assert result == 42

    def test_dump_produces_valid_json(self) -> None:
        dumped = dump_tool_result_to_json({"key": "value"})
        parsed = json.loads(dumped)
        assert parsed == {"key": "value"}

    def test_construct_str_return_returns_raw_json_string(self) -> None:
        # When return type is str, construct_tool_result_from_json returns the raw string
        spec = _make_spec(_echo)
        raw = '"hello"'
        result = construct_tool_result_from_json(spec, raw)
        assert result == raw
