import datetime
from typing import NewType

from pydantic import BaseModel

from .llm import LLMMessage
from .project import ProjectID

ChatSessionID = NewType("ChatSessionID", int)
ChatMessageID = NewType("ChatMessageID", int)


class ChatSession(BaseModel):
    id: ChatSessionID
    project_id: ProjectID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChatMessage(BaseModel):
    id: ChatMessageID
    session_id: ChatSessionID
    message: LLMMessage
    created_at: datetime.datetime
    updated_at: datetime.datetime
