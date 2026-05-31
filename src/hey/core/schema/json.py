import inspect
from typing import Any, Callable, Mapping, Sequence

from pydantic import TypeAdapter, create_model
from pydantic.json_schema import GenerateJsonSchema

type JsonValue = str | int | float | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
_DEFAULT_SCHEMA_DIALECT = GenerateJsonSchema.schema_dialect


def generate_json_schema(o: type | Callable, /) -> Mapping[str, JsonValue]:
    if isinstance(o, type):
        schema = TypeAdapter(o).json_schema()
        return _normalize_schema(schema)
    if callable(o):
        sig = inspect.signature(o)
        field_definitions: dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                raise ValueError(f"Function {o.__name__} cannot use *args/**kwargs for schema generation")
            annotation = Any if param.annotation is inspect.Parameter.empty else param.annotation
            default = ... if param.default is inspect.Parameter.empty else param.default
            field_definitions[name] = (annotation, default)
        model = create_model(
            f"{o.__name__}__parameters",
            **field_definitions,
        )
        schema = model.model_json_schema()
        schema["additionalProperties"] = False
        return _normalize_schema(schema)
    raise ValueError("Input must be a class or a callable")


def _normalize_schema(schema: dict[str, Any]) -> Mapping[str, JsonValue]:
    schema.setdefault("$schema", _DEFAULT_SCHEMA_DIALECT)
    schema.setdefault("$defs", {})
    _strip_property_titles(schema)
    return schema


def _strip_property_titles(schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict):
                prop.pop("title", None)
                _strip_property_titles(prop)
    items = schema.get("items")
    if isinstance(items, dict):
        _strip_property_titles(items)
