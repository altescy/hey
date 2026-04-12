"""Shared fixtures for unit tests."""

import pytest

from hey.domain.entities.llm import (
    AssistantMessage,
    LLMState,
    TextContent,
    ToolCallRecord,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)
from hey.domain.entities.tool import ToolName, ToolSpec

# ---------------------------------------------------------------------------
# LLM message helpers
# ---------------------------------------------------------------------------


def make_user_message(text: str) -> UserMessage:
    return UserMessage(role="user", parts=(TextContent(type="text", text=text),))


def make_assistant_message(text: str, tool_calls: tuple[ToolCallRecord, ...] = ()) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        parts=(TextContent(type="text", text=text),),
        tool_calls=tool_calls,
    )


def make_tool_result_message(tool_call_id: str, text: str) -> ToolResultMessage:
    return ToolResultMessage(
        role="tool_result",
        tool_call_id=tool_call_id,
        parts=(TextContent(type="text", text=text),),
    )


def make_tool_call_record(name: str, args_json: str = "{}", call_id: str = "call-1") -> ToolCallRecord:
    return ToolCallRecord(id=call_id, name=name, args_json=args_json)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_llm_state() -> LLMState:
    return LLMState()


@pytest.fixture
def simple_tool_definition() -> ToolDefinition:
    return ToolDefinition(name="echo", description="Echo the input", parameters={})


@pytest.fixture
def make_tool_spec():
    """Factory fixture: returns a callable that creates a ToolSpec."""

    def _make(
        name: str = "echo",
        description: str = "Echo",
        permission=None,
        func=None,
    ) -> ToolSpec:
        if func is None:

            async def _default_func(text: str) -> str:
                """Default echo tool."""
                return text

            func = _default_func

        from hey.core.schema import generate_function_signature

        sig = generate_function_signature(func)
        return ToolSpec(
            name=ToolName(name),
            description=description,
            func=func,
            permission=permission or {},
            parameters_annotation=sig.parameters_annotation,
            return_annotation=sig.return_annotation,
        )

    return _make
