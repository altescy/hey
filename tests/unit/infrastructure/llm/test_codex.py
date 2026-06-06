import pytest

from hey.domain.entities.llm import AssistantMessage, SystemMessage, TextContent, ToolResultMessage, UserMessage
from hey.infrastructure.llm.codex import (
    CodexQuery,
    _build_request_body,
    _message_to_input_item,
    _raise_for_codex_status,
)


def test_codex_user_message_uses_structured_input_text() -> None:
    message = UserMessage(role="user", parts=(TextContent(type="text", text="hello"),))

    assert _message_to_input_item(message) == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        }
    ]


def test_codex_assistant_message_uses_structured_output_text() -> None:
    message = AssistantMessage(
        role="assistant",
        parts=(TextContent(type="text", text="done"),),
        tool_calls=({"id": "call-1", "name": "echo", "args_json": '{"text":"hello"}'},),
    )

    assert _message_to_input_item(message) == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "done"}],
        },
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "echo",
            "arguments": '{"text":"hello"}',
        },
    ]


def test_codex_system_message_keeps_string_content() -> None:
    message = SystemMessage(role="system", parts=(TextContent(type="text", text="follow instructions"),))

    assert _message_to_input_item(message) == [
        {
            "type": "message",
            "role": "system",
            "content": "follow instructions",
        }
    ]


def test_codex_tool_result_uses_function_call_output() -> None:
    message = ToolResultMessage(
        role="tool_result",
        tool_call_id="call-1",
        parts=(TextContent(type="text", text="ok"),),
    )

    assert _message_to_input_item(message) == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "ok",
        }
    ]


def test_codex_request_body_sets_store_false() -> None:
    query = CodexQuery(system="follow instructions", history=(UserMessage(role="user", parts=()),))

    body = _build_request_body("gpt-5.5", query)

    assert body["model"] == "gpt-5.5"
    assert body["stream"] is True
    assert body["store"] is False
    assert body["instructions"] == "follow instructions"


async def test_raise_for_codex_status_includes_error_body() -> None:
    import httpx

    request = httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses")
    response = httpx.Response(400, request=request, content=b'{"error":"bad model"}')

    with pytest.raises(httpx.HTTPStatusError, match="bad model"):
        await _raise_for_codex_status(response)
