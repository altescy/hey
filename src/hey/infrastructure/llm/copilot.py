"""GitHub Copilot LLM engine.

Uses the Copilot API directly via ``httpx``.

Endpoint routing
----------------
The Copilot API exposes two endpoint families:

* ``/chat/completions`` — OpenAI Chat Completions format (``messages`` array)
* ``/responses``        — OpenAI Responses API format (``input`` array)

Which endpoint a model supports is discovered once at first use via
``GET /models`` and cached for the lifetime of the process.  Models that
only list ``/responses`` in their ``supported_endpoints`` (e.g.
``gpt-5.3-codex``) are routed there; everything else uses
``/chat/completions``.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from hey.domain.entities.llm import (
    Contextualizer,
    Engine,
    FinishReason,
    LLMMessage,
    LLMModelMetadata,
    LLMSignal,
    LLMSpec,
    LLMState,
    TextDelta,
    TextPartDone,
    TextPartStarted,
    ThinkingDelta,
    ThinkingPartDone,
    ThinkingPartStarted,
    ToolCallArgsDelta,
    ToolCallPartDone,
    ToolCallPartStarted,
    ToolDefinition,
    TurnDone,
    Usage,
)

from ._openai_chat import message_to_chat, parse_chat_stream, tool_to_chat
from .auth.copilot import CopilotAuthProvider

# process-level cache: model_id -> set of supported endpoint strings
_MODEL_ENDPOINTS_CACHE: dict[str, set[str]] = {}


async def _get_supported_endpoints(model_id: str, token: str, base_url: str) -> set[str]:
    if model_id in _MODEL_ENDPOINTS_CACHE:
        return _MODEL_ENDPOINTS_CACHE[model_id]

    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {token}", "User-Agent": "hey/0.1.0"},
            )
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                mid = m.get("id", "")
                endpoints = set(m.get("supported_endpoints", []))
                _MODEL_ENDPOINTS_CACHE[mid] = endpoints
    except Exception:
        pass  # fall back to chat/completions on any error

    return _MODEL_ENDPOINTS_CACHE.get(model_id, set())


def _use_responses_api(endpoints: set[str]) -> bool:
    """True when the model only supports /responses (not /chat/completions)."""
    if not endpoints:
        return False
    return "/responses" in endpoints and "/chat/completions" not in endpoints


# ---------------------------------------------------------------------------
# Message/tool serialisation — Chat Completions format
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Message/tool serialisation — Responses API format
# ---------------------------------------------------------------------------


def _tool_to_responses(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool["description"],
        "parameters": tool["parameters"],
    }


def _message_to_input_items(message: LLMMessage) -> list[dict[str, Any]]:
    match message["role"]:
        case "system":
            return [{"role": "system", "content": "".join(p["text"] for p in message["parts"])}]
        case "user":
            return [{"role": "user", "content": "".join(p["text"] for p in message["parts"])}]
        case "assistant":
            items: list[dict[str, Any]] = []
            text = "".join(p["text"] for p in message["parts"])
            if text:
                items.append({"role": "assistant", "content": text})
            for r in message.get("tool_calls") or ():
                items.append(
                    {
                        "type": "function_call",
                        "call_id": r["id"],
                        "name": r["name"],
                        "arguments": r["args_json"],
                    }
                )
            return items
        case "tool_result":
            return [
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": "".join(p["text"] for p in message["parts"]),
                }
            ]
        case _:
            raise ValueError(f"Unknown message role: {message['role']}")


# ---------------------------------------------------------------------------
# Stream parsers
# ---------------------------------------------------------------------------


async def _parse_responses_stream(
    line_iter: AsyncIterator[str],
) -> AsyncIterator[LLMSignal]:
    @dataclasses.dataclass
    class _PartialTC:
        call_id: str
        name: str
        args_buf: str

    text_buf = ""
    text_part_open = False
    text_part_index = 0
    thinking_buf = ""
    thinking_part_open = False
    thinking_part_index = -1
    tc_parts: dict[int, _PartialTC] = {}
    tc_part_index: dict[int, int] = {}
    tc_part_index_base = 1
    next_tc_slot = 0
    finish_reason: FinishReason = "stop"
    usage: Usage = {}

    async for raw_line in line_iter:
        line = raw_line.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break

        event = json.loads(payload)
        event_type: str = event.get("type", "")

        if event_type == "response.completed":
            if u := (event.get("response") or {}).get("usage"):
                if pt := u.get("input_tokens"):
                    usage["input_tokens"] = pt
                if ct := u.get("output_tokens"):
                    usage["output_tokens"] = ct

        elif event_type == "response.reasoning_summary_text.delta":
            delta_text: str = event.get("delta", "")
            if delta_text:
                if not thinking_part_open:
                    thinking_part_open = True
                    thinking_part_index = 0
                    text_part_index = 1
                    tc_part_index_base = 2
                    yield ThinkingPartStarted(type="thinking_part_started", index=thinking_part_index)
                thinking_buf += delta_text
                yield ThinkingDelta(type="thinking_delta", index=thinking_part_index, delta=delta_text)

        elif event_type == "response.output_text.delta":
            delta_text = event.get("delta", "")
            if delta_text:
                if not text_part_open:
                    text_part_open = True
                    yield TextPartStarted(type="text_part_started", index=text_part_index)
                text_buf += delta_text
                yield TextDelta(type="text_delta", index=text_part_index, delta=delta_text)

        elif event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                output_index: int = event.get("output_index", 0)
                call_id: str = item.get("call_id") or ""
                name: str = item.get("name") or ""
                slot = tc_part_index_base + next_tc_slot
                next_tc_slot += 1
                tc_parts[output_index] = _PartialTC(call_id=call_id, name=name, args_buf="")
                tc_part_index[output_index] = slot
                yield ToolCallPartStarted(
                    type="tool_call_part_started",
                    index=slot,
                    tool_call_id=call_id,
                    tool_name=name,
                )

        elif event_type == "response.function_call_arguments.delta":
            output_index = event.get("output_index", 0)
            args_frag: str = event.get("delta", "")
            if output_index in tc_parts and args_frag:
                tc_parts[output_index].args_buf += args_frag
                yield ToolCallArgsDelta(
                    type="tool_call_args_delta",
                    index=tc_part_index[output_index],
                    delta=args_frag,
                )

        elif event_type in ("response.done", "response.failed"):
            resp_obj = event.get("response") or {}
            if resp_obj.get("status") == "incomplete":
                reason = (resp_obj.get("incomplete_details") or {}).get("reason", "length")
                finish_reason = "length" if reason == "max_output_tokens" else "stop"

    if thinking_part_open:
        yield ThinkingPartDone(type="thinking_part_done", index=thinking_part_index, text=thinking_buf)
    if text_part_open:
        yield TextPartDone(type="text_part_done", index=text_part_index, text=text_buf)
    for output_index, part in tc_parts.items():
        slot = tc_part_index.get(output_index, tc_part_index_base + output_index)
        yield ToolCallPartDone(
            type="tool_call_part_done",
            index=slot,
            tool_call_id=part.call_id or f"call_{output_index}",
            tool_name=part.name,
            args_json=part.args_buf,
        )
        finish_reason = "tool_calls"
    yield TurnDone(type="turn_done", reason=finish_reason, usage=usage)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CopilotQuery:
    system: str | None = None
    history: tuple[LLMMessage, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()
    finalizer: ToolDefinition | None = None


class CopilotEngine(Engine[CopilotQuery, LLMSignal]):
    """Streams responses from the GitHub Copilot API."""

    def __init__(self, model: str, auth: CopilotAuthProvider) -> None:
        self._model = model
        self._auth = auth

    @asynccontextmanager
    async def __call__(self, query: CopilotQuery) -> AsyncIterator[AsyncIterator[LLMSignal]]:
        import httpx

        token = await self._auth.get_token()
        base_url = self._auth.api_base_url
        endpoints = await _get_supported_endpoints(self._model, token, base_url)
        use_responses = _use_responses_api(endpoints)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Openai-Intent": "conversation-edits",
            "x-initiator": "user",
        }

        if use_responses:
            input_items: list[dict[str, Any]] = []
            for m in query.history:
                input_items.extend(_message_to_input_items(m))

            tools = [_tool_to_responses(t) for t in query.tools]
            if query.finalizer:
                tools.append(_tool_to_responses(query.finalizer))

            body: dict[str, Any] = {"model": self._model, "input": input_items, "stream": True}
            if query.system:
                body["instructions"] = query.system
            if tools:
                body["tools"] = tools

            url = f"{base_url}/responses"
        else:
            messages: list[dict[str, Any]] = []
            if query.system:
                messages.append({"role": "system", "content": query.system})
            messages.extend(message_to_chat(m) for m in query.history)

            tools = [tool_to_chat(t) for t in query.tools]
            if query.finalizer:
                tools.append(tool_to_chat(query.finalizer))

            body = {"model": self._model, "messages": messages, "stream": True}
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"

            url = f"{base_url}/chat/completions"

        async def _stream() -> AsyncIterator[LLMSignal]:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    if use_responses:
                        async for signal in _parse_responses_stream(resp.aiter_lines()):
                            yield signal
                    else:
                        async for signal in parse_chat_stream(resp.aiter_lines()):
                            yield signal

        yield _stream()


# ---------------------------------------------------------------------------
# Contextualizer
# ---------------------------------------------------------------------------


class CopilotContextualizer(Contextualizer[CopilotQuery, LLMState]):
    def __init__(self, instructions: str | None = None) -> None:
        self._instructions = instructions

    def __call__(self, state: LLMState) -> CopilotQuery:
        return CopilotQuery(
            system=self._instructions or None,
            history=state.history,
            tools=state.tools,
            finalizer=state.finalizer,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


# (context_limit, output_limit) for known GitHub Copilot Chat models.
_MODEL_LIMITS: Final[dict[str, tuple[int, int]]] = {
    "gpt-4o": (128_000, 4_096),
    "gpt-4o-mini": (128_000, 4_096),
    "gpt-4.1": (128_000, 16_384),
    "claude-3.5-sonnet": (200_000, 8_192),
    "claude-3.7-sonnet": (200_000, 16_384),
    "claude-sonnet-4": (200_000, 16_384),
    "gemini-2.0-flash-001": (1_048_576, 8_192),
    "o3-mini": (200_000, 100_000),
    "o4-mini": (200_000, 100_000),
}


def get_copilot_spec(
    *,
    model: str,
    instructions: str | None = None,
    github_domain: str = "github.com",
) -> LLMSpec[CopilotQuery]:
    auth = CopilotAuthProvider(github_domain=github_domain)
    engine = CopilotEngine(model=model, auth=auth)
    contextualizer = CopilotContextualizer(instructions=instructions)
    context_limit, output_limit = _MODEL_LIMITS.get(model, (None, None))
    return LLMSpec(
        engine=engine,
        contextualizer=contextualizer,
        model=LLMModelMetadata(
            provider_id="github-copilot",
            model_id=model,
            context_limit=context_limit,
            output_limit=output_limit,
        ),
    )
