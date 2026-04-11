import json
import typing
from collections.abc import Awaitable, Callable
from types import UnionType
from typing import Any, Final, Union

import colt
from pydantic import TypeAdapter

from hey.core.schema import generate_function_signature, generate_json_schema
from hey.domain.entities.llm import ToolDefinition
from hey.domain.entities.tool import ToolName, ToolParamPermission, ToolSpec

_TOOL_RETURN_TA: Final = TypeAdapter(
    Any,
    config={
        "defer_build": True,
        "ser_json_bytes": "base64",
        "val_json_bytes": "base64",
    },
)


def generate_tool_spec_from_callable(
    func: Callable[..., Awaitable[Any]],
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    permission: ToolParamPermission | None = None,
) -> ToolSpec:
    signature = generate_function_signature(func)
    return ToolSpec(
        name=ToolName(name or signature.name),
        description=description or (func.__doc__.strip() if func.__doc__ else ""),
        func=func,
        permission=permission or {},
        parameters_annotation=signature.parameters_annotation,
        return_annotation=signature.return_annotation,
    )


def generate_tool_definition_from_spec(spec: ToolSpec) -> ToolDefinition:
    return ToolDefinition(
        name=spec.name,
        description=spec.description,
        parameters=generate_json_schema(spec.func),
    )


def construct_tool_parameters_from_json(
    spec: ToolSpec,
    parameters_json: str,
) -> dict[str, Any]:
    return colt.build(json.loads(parameters_json), spec.parameters_annotation, strict=True)


def construct_tool_result_from_json[ReturnT](
    spec: ToolSpec[Any, ReturnT],
    result_json: str,
) -> ReturnT:
    text = result_json
    output_schema = spec.return_annotation
    has_str_schemas = False
    structured_schemas = []
    if output_schema is str:
        has_str_schemas = True
    elif isinstance(output_schema, UnionType):
        for arg in typing.get_args(output_schema):
            if arg is str:
                has_str_schemas = True
            else:
                structured_schemas.append(arg)
    else:
        structured_schemas.append(output_schema)
    if has_str_schemas:
        return result_json  # type: ignore[return-value]
    assert structured_schemas, "finalizer must have at least one non-str return type if it is not str"
    if len(structured_schemas) == 1:
        return colt.build(json.loads(text), structured_schemas[0], strict=True)
    return colt.build(json.loads(text), Union[*structured_schemas], strict=True)  # type: ignore[return-value]


def dump_tool_result_to_json(result: Any) -> str:
    return _TOOL_RETURN_TA.dump_json(result).decode()
