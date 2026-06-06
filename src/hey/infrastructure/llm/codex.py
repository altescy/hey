"""OpenAI Codex LLM engine.

All requests are routed to ``https://chatgpt.com/backend-api/codex/responses``
using the **OpenAI Responses API** format (``input`` array, not ``messages``).
This mirrors the behaviour of the official ``codex`` CLI and of the OpenCode
Codex plugin.

Authentication
--------------
Tokens are managed by :class:`~hey.infrastructure.llm.auth.codex.CodexAuthProvider`,
which transparently refreshes expired tokens.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
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

from .auth.codex import CODEX_API_URL, CodexAuthProvider

# ---------------------------------------------------------------------------
# Serialisation — Responses API format
# ---------------------------------------------------------------------------


def _tool_to_responses(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool["description"],
        "parameters": tool["parameters"],
    }


def _message_to_input_item(message: LLMMessage) -> list[dict[str, Any]]:
    """Convert one LLMMessage to one or more Responses API input items.

    The Responses API uses a flat list of items with ``type`` and ``role``
    rather than a ``messages`` array.  Tool calls and tool results each become
    their own item type.
    """
    match message["role"]:
        case "system":
            return [{"type": "message", "role": "system", "content": "".join(p["text"] for p in message["parts"])}]
        case "user":
            return [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "".join(p["text"] for p in message["parts"])}],
                }
            ]
        case "assistant":
            items: list[dict[str, Any]] = []
            text = "".join(p["text"] for p in message["parts"])
            if text:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                )
            for record in message.get("tool_calls") or ():
                items.append(
                    {
                        "type": "function_call",
                        "call_id": record["id"],
                        "name": record["name"],
                        "arguments": record["args_json"],
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


async def _raise_for_codex_status(resp: Any) -> None:
    if resp.status_code == 403:
        raise PermissionError(
            "Codex: 403 Forbidden — access was denied by the Codex endpoint. "
            "Your ChatGPT subscription may not include Codex access, or your "
            "token may need to be refreshed (re-authenticate to get a new one)."
        )

    if resp.status_code < 400:
        return

    import httpx

    body = (await resp.aread()).decode("utf-8", errors="replace").strip()
    message = f"Codex: HTTP {resp.status_code} {resp.reason_phrase}"
    if body:
        message = f"{message}: {body[:2000]}"
    raise httpx.HTTPStatusError(message, request=resp.request, response=resp)


def _build_request_body(model: str, query: "CodexQuery") -> dict[str, Any]:
    input_items: list[dict[str, Any]] = []
    for message in query.history:
        input_items.extend(_message_to_input_item(message))

    tools = [_tool_to_responses(t) for t in query.tools]
    if query.finalizer:
        tools.append(_tool_to_responses(query.finalizer))

    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "stream": True,
        "store": False,
        # Do not set max_output_tokens — matches Codex CLI behaviour.
    }
    if query.system:
        body["instructions"] = query.system
    if tools:
        body["tools"] = tools
    return body


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CodexQuery:
    system: str | None = None
    history: tuple[LLMMessage, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()
    finalizer: ToolDefinition | None = None


class CodexEngine(Engine[CodexQuery, LLMSignal]):
    """Streams responses from the Codex endpoint at chatgpt.com."""

    def __init__(self, model: str, auth: CodexAuthProvider) -> None:
        self._model = model
        self._auth = auth

    @asynccontextmanager
    async def __call__(self, query: CodexQuery) -> AsyncIterator[AsyncIterator[LLMSignal]]:
        import httpx

        token = await self._auth.get_token()
        account_id = await self._auth.get_account_id()
        body = _build_request_body(self._model, query)

        session_id = str(uuid.uuid4())
        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "originator": "hey",
            "session_id": session_id,
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        async def _stream() -> AsyncIterator[LLMSignal]:
            @dataclasses.dataclass
            class _PartialTC:
                call_id: str
                name: str
                args_buf: str

            text_buf: str = ""
            text_part_open: bool = False
            text_part_index: int = 0

            thinking_buf: str = ""
            thinking_part_open: bool = False
            thinking_part_index: int = -1

            # output_index → partial tool-call state
            tc_parts: dict[int, _PartialTC] = {}
            # output_index → part_index (stable slot in our signal stream)
            tc_part_index: dict[int, int] = {}
            tc_part_index_base: int = 1
            next_tc_slot: int = 0

            finish_reason: FinishReason = "stop"
            usage: Usage = {}

            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream("POST", CODEX_API_URL, json=body, headers=headers) as resp:
                    await _raise_for_codex_status(resp)
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:") :].strip()
                        if payload == "[DONE]":
                            break

                        event = json.loads(payload)
                        event_type: str = event.get("type", "")

                        # --- usage ---
                        if event_type == "response.completed":
                            resp_obj = event.get("response") or {}
                            if u := resp_obj.get("usage"):
                                if pt := u.get("input_tokens"):
                                    usage["input_tokens"] = pt
                                if ct := u.get("output_tokens"):
                                    usage["output_tokens"] = ct

                        # --- thinking (summary delta) ---
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

                        elif event_type == "response.reasoning_summary_text.done":
                            pass  # handled at stream end

                        # --- text ---
                        elif event_type == "response.output_text.delta":
                            delta_text = event.get("delta", "")
                            if delta_text:
                                if not text_part_open:
                                    text_part_open = True
                                    yield TextPartStarted(type="text_part_started", index=text_part_index)
                                text_buf += delta_text
                                yield TextDelta(type="text_delta", index=text_part_index, delta=delta_text)

                        # --- tool calls ---
                        elif event_type == "response.function_call_arguments.delta":
                            output_index: int = event.get("output_index", 0)
                            args_frag: str = event.get("delta", "")
                            if output_index in tc_parts and args_frag:
                                tc_parts[output_index].args_buf += args_frag
                                yield ToolCallArgsDelta(
                                    type="tool_call_args_delta",
                                    index=tc_part_index[output_index],
                                    delta=args_frag,
                                )

                        elif event_type == "response.output_item.added":
                            item = event.get("item") or {}
                            if item.get("type") == "function_call":
                                output_index = event.get("output_index", 0)
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

                        elif event_type == "response.output_item.done":
                            item = event.get("item") or {}
                            if item.get("type") == "function_call":
                                output_index = event.get("output_index", 0)

                        elif event_type in ("response.done", "response.failed"):
                            resp_obj = event.get("response") or {}
                            status = resp_obj.get("status", "")
                            if status == "incomplete":
                                inc = resp_obj.get("incomplete_details") or {}
                                reason = inc.get("reason", "length")
                                finish_reason = "length" if reason == "max_output_tokens" else "stop"
                            # Do NOT force "stop" here — tc_parts (if any) will set "tool_calls" below.

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

        yield _stream()


# ---------------------------------------------------------------------------
# Contextualizer
# ---------------------------------------------------------------------------


class CodexContextualizer(Contextualizer[CodexQuery, LLMState]):
    def __init__(self, instructions: str | None = None) -> None:
        self._instructions = instructions

    def __call__(self, state: LLMState) -> CodexQuery:
        return CodexQuery(
            system=self._instructions or None,
            history=state.history,
            tools=state.tools,
            finalizer=state.finalizer,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


# (context_limit, output_limit) for known Codex (OpenAI Responses) models.
_MODEL_LIMITS: Final[dict[str, tuple[int, int]]] = {
    "gpt-4.1": (1_047_576, 32_768),
    "gpt-4.1-mini": (1_047_576, 32_768),
    "gpt-4.1-nano": (1_047_576, 32_768),
    "gpt-4o": (128_000, 16_384),
    "gpt-4o-mini": (128_000, 16_384),
    "o3": (200_000, 100_000),
    "o3-mini": (200_000, 100_000),
    "o4-mini": (200_000, 100_000),
}


def get_codex_spec(
    *,
    model: str = "o4-mini",
    instructions: str | None = None,
) -> LLMSpec[CodexQuery]:
    auth = CodexAuthProvider()
    engine = CodexEngine(model=model, auth=auth)
    contextualizer = CodexContextualizer(instructions=instructions)
    context_limit, output_limit = _MODEL_LIMITS.get(model, (None, None))
    return LLMSpec(
        engine=engine,
        contextualizer=contextualizer,
        model=LLMModelMetadata(
            provider_id="codex",
            model_id=model,
            context_limit=context_limit,
            output_limit=output_limit,
        ),
    )
