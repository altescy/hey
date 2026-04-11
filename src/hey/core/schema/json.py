from typing import Callable, Mapping, Sequence

from colt import JsonSchemaGenerator

type JsonValue = str | int | float | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]


def generate_json_schema(o: type | Callable, /) -> Mapping[str, JsonValue]:
    return JsonSchemaGenerator(strict=True)(o)
