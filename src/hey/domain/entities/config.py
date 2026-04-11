from typing import NewType

from pydantic import BaseModel, Field

ProjectID = NewType("ProjectID", str)


class ChatConfig(BaseModel):
    model: str = "gpt-5.2"
    instructions: str = "You are a helpful assistant."


class HeyConfig(BaseModel):
    chat: ChatConfig = Field(default_factory=ChatConfig)
