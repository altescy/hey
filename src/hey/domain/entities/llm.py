import dataclasses
from collections.abc import Mapping
from typing import Annotated, Literal, TypedDict

from pydantic import Discriminator

from hey.core.agent import Contextualizer, Engine
from hey.core.schema import JsonValue


class TextPartStarted(TypedDict):
    type: Literal["text_part_started"]
    index: int


class TextDelta(TypedDict):
    type: Literal["text_delta"]
    index: int
    delta: str


class TextPartDone(TypedDict):
    type: Literal["text_part_done"]
    index: int
    text: str  # fully accumulated text of this part


class ToolCallPartStarted(TypedDict):
    type: Literal["tool_call_part_started"]
    index: int
    tool_call_id: str
    tool_name: str


class ToolCallArgsDelta(TypedDict):
    type: Literal["tool_call_args_delta"]
    index: int
    delta: str


class ToolCallPartDone(TypedDict):
    type: Literal["tool_call_part_done"]
    index: int
    tool_call_id: str
    tool_name: str
    args_json: str  # fully accumulated JSON-serialized args of this part


class TurnDone(TypedDict):
    type: Literal["turn_done"]


type LLMSignal = Annotated[
    TextPartStarted | TextDelta | TextPartDone | ToolCallPartStarted | ToolCallArgsDelta | ToolCallPartDone | TurnDone,
    Discriminator("type"),
]


class TextContent(TypedDict):
    type: Literal["text"]
    text: str


type ContentPart = TextContent


class ToolCallRecord(TypedDict):
    id: str
    name: str
    args_json: str


class SystemMessage(TypedDict):
    role: Literal["system"]
    parts: tuple[ContentPart, ...]


class UserMessage(TypedDict):
    role: Literal["user"]
    parts: tuple[ContentPart, ...]


class AssistantMessage(TypedDict):
    role: Literal["assistant"]
    parts: tuple[ContentPart, ...]
    tool_calls: tuple[ToolCallRecord, ...]


class ToolResultMessage(TypedDict):
    role: Literal["tool_result"]
    tool_call_id: str
    parts: tuple[ContentPart, ...]


type LLMMessage = Annotated[
    SystemMessage | UserMessage | AssistantMessage | ToolResultMessage,
    Discriminator("role"),
]


class ToolDefinition(TypedDict):
    name: str
    description: str
    parameters: Mapping[str, JsonValue]


@dataclasses.dataclass(frozen=True)
class LLMState:
    history: tuple[LLMMessage, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()
    finalizer: ToolDefinition | None = None


type LLMEngine[QueryT] = Engine[QueryT, LLMSignal]


@dataclasses.dataclass(frozen=True, slots=True)
class LLMSpec[QueryT]:
    engine: LLMEngine[QueryT]
    contextualizer: Contextualizer[QueryT, LLMState]


@dataclasses.dataclass(frozen=True)
class EmitLLMSignal:
    signal: LLMSignal


@dataclasses.dataclass(frozen=True)
class EmitLLMMessage:
    message: LLMMessage


@dataclasses.dataclass(frozen=True)
class EmitToolResult:
    message: ToolResultMessage
    status: Literal["success", "error", "denied"]


type LLMEvent = EmitLLMSignal | EmitLLMMessage | EmitToolResult
