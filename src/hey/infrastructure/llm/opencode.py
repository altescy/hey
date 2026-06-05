"""OpenCode Zen / Go LLM engine.

Streams responses from the OpenCode managed API endpoints using the
OpenAI Chat Completions format.

Authentication
--------------
Set the ``OPENCODE_API_KEY`` environment variable, or pass ``api_key``
explicitly to :func:`get_opencode_spec`.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from hey.domain.entities.llm import (
    Contextualizer,
    Engine,
    LLMModelMetadata,
    LLMSignal,
    LLMSpec,
    LLMState,
    ToolDefinition,
)

from ._openai_chat import message_to_chat, parse_chat_stream, tool_to_chat


@dataclasses.dataclass(frozen=True)
class OpenCodeQuery:
    system: str | None = None
    history: tuple[Any, ...] = ()  # LLMMessage
    tools: tuple[ToolDefinition, ...] = ()
    finalizer: ToolDefinition | None = None


class OpenCodeEngine(Engine[OpenCodeQuery, LLMSignal]):
    """Streams responses from OpenCode Zen or Go endpoints."""

    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key = api_key

    @asynccontextmanager
    async def __call__(self, query: OpenCodeQuery) -> AsyncIterator[AsyncIterator[LLMSignal]]:
        import httpx

        messages: list[dict[str, Any]] = []
        if query.system:
            messages.append({"role": "system", "content": query.system})
        messages.extend(message_to_chat(m) for m in query.history)

        tools = [tool_to_chat(t) for t in query.tools]
        if query.finalizer:
            tools.append(tool_to_chat(query.finalizer))

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async def _stream() -> AsyncIterator[LLMSignal]:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", self._base_url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    async for signal in parse_chat_stream(resp.aiter_lines()):
                        yield signal

        yield _stream()


class OpenCodeContextualizer(Contextualizer[OpenCodeQuery, LLMState]):
    def __init__(self, instructions: str | None = None) -> None:
        self._instructions = instructions

    def __call__(self, state: LLMState) -> OpenCodeQuery:
        return OpenCodeQuery(
            system=self._instructions or None,
            history=state.history,
            tools=state.tools,
            finalizer=state.finalizer,
        )


# OpenCode is a proxy to many providers; only well-known passthroughs are listed
# here. Unlisted models fall back to None and disable auto-compaction.
_MODEL_LIMITS: Final[dict[str, tuple[int, int]]] = {
    "claude-3-5-sonnet": (200_000, 8_192),
    "claude-3-7-sonnet": (200_000, 64_000),
    "claude-sonnet-4": (200_000, 64_000),
    "claude-sonnet-4-5": (200_000, 64_000),
    "claude-opus-4-7": (200_000, 32_000),
    "gpt-4o": (128_000, 16_384),
    "gpt-4.1": (1_047_576, 32_768),
}


def get_opencode_spec(
    *,
    model: str,
    base_url: str,
    instructions: str | None = None,
    api_key: str | None = None,
) -> LLMSpec[OpenCodeQuery]:
    key = api_key or os.environ.get("OPENCODE_API_KEY")
    if not key:
        raise RuntimeError(
            "OpenCode API key is required. Set the OPENCODE_API_KEY environment variable or pass api_key explicitly."
        )
    engine = OpenCodeEngine(model=model, base_url=base_url, api_key=key)
    contextualizer = OpenCodeContextualizer(instructions=instructions)
    context_limit, output_limit = _MODEL_LIMITS.get(model, (None, None))
    return LLMSpec(
        engine=engine,
        contextualizer=contextualizer,
        model=LLMModelMetadata(
            provider_id="opencode",
            model_id=model,
            context_limit=context_limit,
            output_limit=output_limit,
        ),
    )
