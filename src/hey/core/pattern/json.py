import fnmatch
import json
import re
from types import NoneType

_ESCAPE_CHAR_PATTERN = re.compile(r"([\.\*\?\[\]\!])")


def _escape(s: str) -> str:
    return _ESCAPE_CHAR_PATTERN.sub(r"\\\1", s)


def _flatten(o) -> list[str]:
    if isinstance(o, str):
        return [_escape(o)]
    if isinstance(o, (int, float, bool, NoneType)):
        return [_escape(json.dumps(o))]
    if isinstance(o, list):
        return [f"{index}.{part}" for index, item in enumerate(o) for part in _flatten(item)]
    if isinstance(o, dict):
        return [f"{_escape(key)}.{part}" for key, value in o.items() for part in _flatten(value)]
    raise ValueError(f"unsupported type: {type(o)}")


def json_match(json_string: str, /, pattern: str) -> bool:
    for part in _flatten(json.loads(json_string)):
        if fnmatch.fnmatch(part, pattern):
            return True
    return False
