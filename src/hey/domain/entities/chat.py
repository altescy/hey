import datetime
from typing import Any, Literal, NewType

from pydantic import BaseModel, Field

from .llm import LLMMessage
from .project import ProjectID

ChatSessionID = NewType("ChatSessionID", int)
ChatMessageID = NewType("ChatMessageID", int)
ChatMessageKind = Literal["normal", "summary"]


class ChatSession(BaseModel):
    id: ChatSessionID
    project_id: ProjectID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChatMessage(BaseModel):
    id: ChatMessageID
    session_id: ChatSessionID
    message: LLMMessage
    kind: ChatMessageKind = "normal"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime.datetime
    updated_at: datetime.datetime
