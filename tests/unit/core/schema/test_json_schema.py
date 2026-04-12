"""Tests for hey.core.schema.json (generate_json_schema)."""

from typing import TypedDict

from hey.core.schema.json import generate_json_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FlatParams(TypedDict):
    a: int
    b: str


class _NestedInner(TypedDict):
    value: float


class _NestedOuter(TypedDict):
    inner: _NestedInner
    name: str


async def _func_two_params(x: int, y: str) -> bool: ...


async def _func_no_params() -> str: ...


# ---------------------------------------------------------------------------
# TestGenerateJsonSchema
# ---------------------------------------------------------------------------


class TestGenerateJsonSchema:
    def test_int_type(self) -> None:
        schema = generate_json_schema(int)
        assert schema["type"] == "integer"

    def test_str_type(self) -> None:
        schema = generate_json_schema(str)
        assert schema["type"] == "string"

    def test_float_type(self) -> None:
        schema = generate_json_schema(float)
        assert schema["type"] == "number"

    def test_bool_type(self) -> None:
        schema = generate_json_schema(bool)
        assert schema["type"] == "boolean"

    def test_typed_dict_is_object(self) -> None:
        schema = generate_json_schema(_FlatParams)
        assert schema["type"] == "object"

    def test_typed_dict_properties(self) -> None:
        schema = generate_json_schema(_FlatParams)
        props = schema["properties"]
        assert isinstance(props, dict)
        assert props["a"] == {"type": "integer"}
        assert props["b"] == {"type": "string"}

    def test_typed_dict_required_fields(self) -> None:
        schema = generate_json_schema(_FlatParams)
        required = schema["required"]
        assert isinstance(required, list)
        assert set(required) == {"a", "b"}

    def test_typed_dict_title(self) -> None:
        schema = generate_json_schema(_FlatParams)
        assert schema["title"] == "_FlatParams"

    def test_callable_schema_is_object(self) -> None:
        schema = generate_json_schema(_func_two_params)
        assert schema["type"] == "object"

    def test_callable_schema_properties(self) -> None:
        schema = generate_json_schema(_func_two_params)
        props = schema["properties"]
        assert isinstance(props, dict)
        assert props["x"] == {"type": "integer"}
        assert props["y"] == {"type": "string"}

    def test_callable_schema_no_additional_properties(self) -> None:
        schema = generate_json_schema(_func_two_params)
        assert schema.get("additionalProperties") is False

    def test_returns_mapping(self) -> None:
        from collections.abc import Mapping

        schema = generate_json_schema(int)
        assert isinstance(schema, Mapping)

    def test_schema_version_present(self) -> None:
        schema = generate_json_schema(str)
        assert "$schema" in schema

    def test_defs_key_present(self) -> None:
        schema = generate_json_schema(str)
        assert "$defs" in schema
