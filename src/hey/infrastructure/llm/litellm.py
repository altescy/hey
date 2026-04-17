import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, assert_never

from hey.domain.entities.llm import (
    Contextualizer,
    Engine,
    FinishReason,
    LLMMessage,
    LLMSignal,
    LLMSpec,
    LLMState,
    SystemMessage,
    TextContent,
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


@dataclasses.dataclass(frozen=True)
class LiteLLMQuery:
    system: str | None = None
    history: tuple[LLMMessage, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()
    finalizer: ToolDefinition | None = None


class LiteLLMEngine(Engine[LiteLLMQuery, LLMSignal]):
    def __init__(self, model: str) -> None:
        self._model = model

    @staticmethod
    def _tool_to_litellm(tool: ToolDefinition) -> dict[str, Any]:
        func: dict[str, Any] = {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
        return {"type": "function", "function": func}

    @staticmethod
    def _message_to_litellm(message: LLMMessage) -> dict[str, Any]:
        match message["role"]:
            case "system":
                return {
                    "role": "system",
                    "content": "".join(part["text"] for part in message["parts"]),
                }
            case "user":
                return {
                    "role": "user",
                    "content": "".join(part["text"] for part in message["parts"]),
                }
            case "assistant":
                return {
                    "role": "assistant",
                    "content": "".join(part["text"] for part in message["parts"]),
                    **(
                        {
                            "tool_calls": [
                                {
                                    "id": record["id"],
                                    "function": {
                                        "name": record["name"],
                                        "arguments": record["args_json"],
                                    },
                                    "type": "function",
                                }
                                for record in message["tool_calls"]
                            ],
                        }
                        if message.get("tool_calls")
                        else {}
                    ),
                }
            case "tool_result":
                return {
                    "role": "tool",
                    "tool_call_id": message["tool_call_id"],
                    "content": "".join(part["text"] for part in message["parts"]),
                }
            case _:
                assert_never(message)

    @asynccontextmanager
    async def __call__(self, query: LiteLLMQuery) -> AsyncIterator[AsyncIterator[LLMSignal]]:
        import litellm

        async def _stream() -> AsyncIterator[LLMSignal]:
            @dataclasses.dataclass
            class _PartialTC:
                tool_call_id: str
                tool_name: str
                args_buf: str

            # Part state
            text_buf: str = ""
            text_part_open: bool = False
            text_part_index: int = 0

            thinking_buf: str = ""
            thinking_part_open: bool = False
            thinking_part_index: int = -1  # will be assigned when opened

            tc_parts: dict[int, _PartialTC] = {}
            tc_part_index_base: int = 1

            response = await litellm.acompletion(
                model=self._model,
                messages=[
                    *([{"role": "system", "content": query.system}] if query.system else ()),
                    *[self._message_to_litellm(message) for message in query.history],
                ],
                tools=[
                    *(self._tool_to_litellm(tool) for tool in query.tools),
                    *((self._tool_to_litellm(query.finalizer),) if query.finalizer else ()),
                ],
                stream=True,
            )

            assert isinstance(response, AsyncIterator)

            finish_reason: FinishReason = "stop"
            usage: Usage = {}

            async for chunk in response:
                if chunk_usage := getattr(chunk, "usage", None):
                    usage = {}
                    if prompt_tokens := getattr(chunk_usage, "prompt_tokens", None):
                        usage["input_tokens"] = prompt_tokens
                    if completion_tokens := getattr(chunk_usage, "completion_tokens", None):
                        usage["output_tokens"] = completion_tokens

                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue

                delta = choice.delta

                # --- thinking ---
                thinking_text: str | None = getattr(delta, "thinking", None) or getattr(
                    delta, "reasoning_content", None
                )
                if thinking_text:
                    if not thinking_part_open:
                        thinking_part_open = True
                        thinking_part_index = 0
                        # Push text part index up
                        text_part_index = 1
                        tc_part_index_base = 2
                        yield ThinkingPartStarted(type="thinking_part_started", index=thinking_part_index)
                    thinking_buf += thinking_text
                    yield ThinkingDelta(type="thinking_delta", index=thinking_part_index, delta=thinking_text)

                # --- text ---
                if delta.content:
                    if not text_part_open:
                        text_part_open = True
                        yield TextPartStarted(type="text_part_started", index=text_part_index)
                    text_buf += delta.content
                    yield TextDelta(type="text_delta", index=text_part_index, delta=delta.content)

                # --- tool calls ---
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        part_index = tc_part_index_base + idx

                        if idx not in tc_parts:
                            tc_id = getattr(tc, "id", None) or ""
                            tc_name = (tc.function.name if tc.function else None) or ""
                            tc_parts[idx] = _PartialTC(
                                tool_call_id=tc_id,
                                tool_name=tc_name,
                                args_buf="",
                            )
                            yield ToolCallPartStarted(
                                type="tool_call_part_started",
                                index=part_index,
                                tool_call_id=tc_id,
                                tool_name=tc_name,
                            )
                        else:
                            part = tc_parts[idx]
                            if tc.id and not part.tool_call_id:  # type: ignore[attr-defined]
                                part.tool_call_id = tc.id  # type: ignore[attr-defined]
                            if tc.function and tc.function.name and not part.tool_name:
                                part.tool_name = tc.function.name

                        args_frag = tc.function.arguments if tc.function and tc.function.arguments else ""
                        if args_frag:
                            tc_parts[idx].args_buf += args_frag
                            yield ToolCallArgsDelta(type="tool_call_args_delta", index=part_index, delta=args_frag)

                if choice.finish_reason in ("stop", "tool_calls", "length", "content_filter"):
                    finish_reason = choice.finish_reason

            if thinking_part_open:
                yield ThinkingPartDone(
                    type="thinking_part_done",
                    index=thinking_part_index,
                    text=thinking_buf,
                )

            if text_part_open:
                yield TextPartDone(type="text_part_done", index=text_part_index, text=text_buf)

            for idx, part in tc_parts.items():
                part_index = tc_part_index_base + idx
                yield ToolCallPartDone(
                    type="tool_call_part_done",
                    index=part_index,
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    args_json=part.args_buf,
                )

            yield TurnDone(type="turn_done", reason=finish_reason, usage=usage)

        yield _stream()


class LiteLLMContextualizer(Contextualizer[LiteLLMQuery, LLMState]):
    def __init__(self, instructions: str | None = None) -> None:
        self._instructions = instructions

    def __call__(self, state: LLMState) -> LiteLLMQuery:
        history = state.history
        if self._instructions:
            history = (
                SystemMessage(role="system", parts=(TextContent(type="text", text=self._instructions),)),
            ) + history
        return LiteLLMQuery(
            history=history,
            tools=state.tools,
            finalizer=state.finalizer,
        )


def get_litellm_spec(
    *,
    model: str,
    instructions: str | None = None,
) -> LLMSpec[LiteLLMQuery]:
    engine = LiteLLMEngine(model=model)
    contextualizer = LiteLLMContextualizer(instructions=instructions)
    return LLMSpec(engine=engine, contextualizer=contextualizer)
