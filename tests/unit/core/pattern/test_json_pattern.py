"""Tests for hey.core.pattern.json (json_match)."""

import json

import pytest

from hey.core.pattern.json import json_match


class TestJsonMatch:
    # ------------------------------------------------------------------
    # Scalar values
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "json_string, pattern, expected",
        [
            # strings
            ('"hello"', "hello", True),
            ('"hello"', "hell*", True),
            ('"hello"', "world", False),
            # integers
            ("42", "42", True),
            ("42", "4*", True),
            ("42", "99", False),
            # floats: the decimal point is escaped as '\.' in flattened form,
            # so the pattern must also escape it (or use a wildcard).
            ("3.14", r"3\.14", True),
            ("3.14", "3*", True),
            # booleans
            ("true", "true", True),
            ("false", "false", True),
            ("true", "false", False),
            # null
            ("null", "null", True),
            ("null", "none", False),
        ],
    )
    def test_scalar(self, json_string: str, pattern: str, expected: bool) -> None:
        assert json_match(json_string, pattern) is expected

    # ------------------------------------------------------------------
    # Flat objects
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "obj, pattern, expected",
        [
            ({"key": "value"}, "key.value", True),
            ({"key": "value"}, "key.val*", True),
            ({"key": "value"}, "other.value", False),
            ({"a": 1, "b": 2}, "a.1", True),
            ({"a": 1, "b": 2}, "b.2", True),
            ({"a": 1, "b": 2}, "a.2", False),
        ],
    )
    def test_flat_object(self, obj: dict, pattern: str, expected: bool) -> None:
        assert json_match(json.dumps(obj), pattern) is expected

    # ------------------------------------------------------------------
    # Nested objects
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "obj, pattern, expected",
        [
            ({"a": {"b": "c"}}, "a.b.c", True),
            ({"a": {"b": "c"}}, "a.b.*", True),
            ({"a": {"b": "c"}}, "a.*.c", True),
            ({"a": {"b": "c"}}, "*.b.c", True),
            ({"a": {"b": "c"}}, "x.b.c", False),
        ],
    )
    def test_nested_object(self, obj: dict, pattern: str, expected: bool) -> None:
        assert json_match(json.dumps(obj), pattern) is expected

    # ------------------------------------------------------------------
    # Arrays
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "obj, pattern, expected",
        [
            (["a", "b", "c"], "0.a", True),
            (["a", "b", "c"], "1.b", True),
            (["a", "b", "c"], "2.c", True),
            (["a", "b", "c"], "0.b", False),
            ([{"x": 1}], "0.x.1", True),
            ([{"x": 1}], "0.x.2", False),
        ],
    )
    def test_array(self, obj: list, pattern: str, expected: bool) -> None:
        assert json_match(json.dumps(obj), pattern) is expected

    # ------------------------------------------------------------------
    # Wildcard patterns
    # ------------------------------------------------------------------

    def test_wildcard_matches_any_key(self) -> None:
        obj = {"foo": "bar", "baz": "bar"}
        assert json_match(json.dumps(obj), "*.bar") is True

    def test_wildcard_matches_across_levels(self) -> None:
        # In this implementation "*" is passed to fnmatch, which matches any
        # characters including the "." path separator.  So "*.c" matches the
        # flattened path "a.b.c" because * covers "a.b".
        obj = {"a": {"b": "c"}}
        assert json_match(json.dumps(obj), "*.c") is True

    def test_question_mark_matches_single_char(self) -> None:
        assert json_match('"ab"', "a?") is True
        assert json_match('"abc"', "a?") is False

    # ------------------------------------------------------------------
    # Special characters in keys / values are escaped
    # ------------------------------------------------------------------

    def test_dot_in_key_is_treated_as_literal(self) -> None:
        obj = {"a.b": "v"}
        # The key "a.b" is escaped so "a.b.v" should match its flattened form
        assert json_match(json.dumps(obj), "a\\.b.v") is True

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="unsupported type"):
            # Pass a raw Python object (not JSON string) via internal _flatten
            from hey.core.pattern.json import _flatten

            _flatten(object())
