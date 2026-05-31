"""OpenAI Chat Completions serialisation and SSE stream parser.

Used by backends that speak the standard ``/chat/completions`` streaming
endpoint (e.g. GitHub Copilot, OpenCode Zen/Go).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from typing import Any

from hey.domain.entities.llm import (
    FinishReason,
    LLMMessage,
    LLMSignal,
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


def tool_to_chat(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }


def message_to_chat(message: LLMMessage) -> dict[str, Any]:
    match message["role"]:
        case "system":
            return {"role": "system", "content": "".join(p["text"] for p in message["parts"])}
        case "user":
            return {"role": "user", "content": "".join(p["text"] for p in message["parts"])}
        case "assistant":
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(p["text"] for p in message["parts"]),
            }
            if message.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": r["id"],
                        "type": "function",
                        "function": {"name": r["name"], "arguments": r["args_json"]},
                    }
                    for r in message["tool_calls"]
                ]
            return msg
        case "tool_result":
            return {
                "role": "tool",
                "tool_call_id": message["tool_call_id"],
                "content": "".join(p["text"] for p in message["parts"]),
            }
        case _:
            raise ValueError(f"Unknown message role: {message['role']}")


async def parse_chat_stream(
    line_iter: AsyncIterator[str],
) -> AsyncIterator[LLMSignal]:
    @dataclasses.dataclass
    class _PartialTC:
        tool_call_id: str
        tool_name: str
        args_buf: str

    text_buf = ""
    text_part_open = False
    text_part_index = 0
    thinking_buf = ""
    thinking_part_open = False
    thinking_part_index = -1
    tc_parts: dict[int, _PartialTC] = {}
    tc_part_index_base = 1
    finish_reason: FinishReason = "stop"
    usage: Usage = {}

    async for raw_line in line_iter:
        line = raw_line.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break

        chunk = json.loads(payload)

        if u := chunk.get("usage"):
            if pt := u.get("prompt_tokens"):
                usage["input_tokens"] = pt
            if ct := u.get("completion_tokens"):
                usage["output_tokens"] = ct
            if rd := (u.get("completion_tokens_details") or {}).get("reasoning_tokens"):
                usage["reasoning_tokens"] = rd

        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}

        thinking_text: str | None = delta.get("reasoning_text") or delta.get("reasoning_content")
        if thinking_text:
            if not thinking_part_open:
                thinking_part_open = True
                thinking_part_index = 0
                text_part_index = 1
                tc_part_index_base = 2
                yield ThinkingPartStarted(type="thinking_part_started", index=thinking_part_index)
            thinking_buf += thinking_text
            yield ThinkingDelta(type="thinking_delta", index=thinking_part_index, delta=thinking_text)

        if content := delta.get("content"):
            if not text_part_open:
                text_part_open = True
                yield TextPartStarted(type="text_part_started", index=text_part_index)
            text_buf += content
            yield TextDelta(type="text_delta", index=text_part_index, delta=content)

        for tc in delta.get("tool_calls") or []:
            idx: int = tc["index"]
            part_index = tc_part_index_base + idx
            if idx not in tc_parts:
                tc_id = tc.get("id") or ""
                tc_name = (tc.get("function") or {}).get("name") or ""
                tc_parts[idx] = _PartialTC(tool_call_id=tc_id, tool_name=tc_name, args_buf="")
                yield ToolCallPartStarted(
                    type="tool_call_part_started",
                    index=part_index,
                    tool_call_id=tc_id,
                    tool_name=tc_name,
                )
            else:
                part = tc_parts[idx]
                if tc.get("id") and not part.tool_call_id:
                    part.tool_call_id = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name") and not part.tool_name:
                    part.tool_name = fn["name"]

            args_frag = (tc.get("function") or {}).get("arguments") or ""
            if args_frag:
                tc_parts[idx].args_buf += args_frag
                yield ToolCallArgsDelta(type="tool_call_args_delta", index=part_index, delta=args_frag)

        if choice.get("finish_reason") in ("stop", "tool_calls", "length", "content_filter"):
            finish_reason = choice["finish_reason"]

    if thinking_part_open:
        yield ThinkingPartDone(type="thinking_part_done", index=thinking_part_index, text=thinking_buf)
    if text_part_open:
        yield TextPartDone(type="text_part_done", index=text_part_index, text=text_buf)
    for idx, part in tc_parts.items():
        part_index = tc_part_index_base + idx
        yield ToolCallPartDone(
            type="tool_call_part_done",
            index=part_index,
            tool_call_id=part.tool_call_id or f"call_{idx}",
            tool_name=part.tool_name,
            args_json=part.args_buf,
        )
        finish_reason = "tool_calls"
    yield TurnDone(type="turn_done", reason=finish_reason, usage=usage)
