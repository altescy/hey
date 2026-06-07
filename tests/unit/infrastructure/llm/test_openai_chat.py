from collections.abc import AsyncIterator

from hey.infrastructure.llm._openai_chat import parse_chat_stream


async def test_parse_chat_stream_closes_upstream_iterator_on_done() -> None:
    closed = False

    async def lines() -> AsyncIterator[str]:
        nonlocal closed
        try:
            yield 'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}'
            yield "data: [DONE]"
            yield 'data: {"choices":[{"delta":{"content":"unreachable"}}]}'
        finally:
            closed = True

    signals = [signal async for signal in parse_chat_stream(lines())]

    assert closed is True
    assert signals[-1]["type"] == "turn_done"
