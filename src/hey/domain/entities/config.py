from pydantic import BaseModel, Field

from .tool import ToolPermission


class ChatConfig(BaseModel):
    model: str = "gpt-5.2"
    instructions: str = "You are a helpful assistant."
    permission: ToolPermission = Field(default_factory=dict)


class HeyConfig(BaseModel):
    chat: ChatConfig = Field(default_factory=ChatConfig)
