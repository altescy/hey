from __future__ import annotations

import platform

from hey.domain.entities.sandbox import PermissionProfile
from hey.infrastructure.sandbox.exceptions import SandboxUnavailableError
from hey.infrastructure.sandbox.macos import MacOSSandboxRunner
from hey.infrastructure.sandbox.noop import NoopSandboxRunner
from hey.infrastructure.sandbox.protocol import SandboxRunner


def build_sandbox_runner(profile: PermissionProfile) -> SandboxRunner:
    if profile.enforcement == "disabled":
        return NoopSandboxRunner()
    if profile.enforcement == "external":
        raise SandboxUnavailableError("external sandbox enforcement is not implemented")

    system = platform.system()
    if system == "Darwin":
        return MacOSSandboxRunner()
    raise SandboxUnavailableError(f"managed sandbox enforcement is not implemented for {system}")
