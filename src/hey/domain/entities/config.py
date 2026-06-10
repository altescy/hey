from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from .tool import ToolPermission

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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


class ChatCompactionConfig(BaseModel):
    enabled: bool = True
    auto: bool = False
    threshold_ratio: float = Field(default=0.8, gt=0, le=1)
    max_context_tokens: int | None = Field(default=None, gt=0)
    reserve_output_tokens: int = Field(default=20_000, ge=0)
    tail_turns: int = Field(default=2, ge=0)
    preserve_recent_tokens: int | None = Field(default=None, gt=0)


class SandboxConfig(BaseModel):
    enabled: bool = True
    enforcement: Literal["managed", "external", "disabled"] = "managed"
    filesystem: Literal["read_only", "workspace_write", "unrestricted", "custom"] = "workspace_write"
    network: Literal["restricted", "enabled", "proxy_only"] = "restricted"


class ChatConfig(BaseModel):
    model: NonEmptyString
    instructions: str | None = None
    permission: ToolPermission = Field(default_factory=dict)
    session_timeout: float = Field(default=3600.0, description="Seconds of inactivity before a new session is started.")
    compaction: ChatCompactionConfig = Field(default_factory=ChatCompactionConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    mcp: Mapping[str, MCPServerConfig] = Field(default_factory=dict)


class HeyConfig(BaseModel):
    chat: ChatConfig
