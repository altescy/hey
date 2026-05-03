from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .tool import ToolPermission


class MCPServerConfig(BaseModel):
    transport: Literal["stdio", "streamable_http"]
    enabled: bool = True
    command: list[str] = Field(default_factory=list)
    url: str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0

    @model_validator(mode="after")
    def _validate_transport(self) -> "MCPServerConfig":
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires non-empty command")
        if self.transport == "streamable_http" and not self.url:
            raise ValueError("streamable_http transport requires url")
        return self


class ChatConfig(BaseModel):
    model: str = "gpt-5.2"
    instructions: str = "You are a helpful assistant."
    permission: ToolPermission = Field(default_factory=dict)
    session_timeout: float = Field(default=3600.0, description="Seconds of inactivity before a new session is started.")
    mcp: Mapping[str, MCPServerConfig] = Field(default_factory=dict)


class HeyConfig(BaseModel):
    chat: ChatConfig = Field(default_factory=ChatConfig)
