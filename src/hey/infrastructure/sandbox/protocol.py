from __future__ import annotations

from typing import Protocol

from hey.domain.entities.sandbox import SandboxExecRequest, SandboxExecResult


class SandboxRunner(Protocol):
    async def run(self, request: SandboxExecRequest) -> SandboxExecResult: ...
