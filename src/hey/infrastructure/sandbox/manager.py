from __future__ import annotations

import platform

from hey.domain.entities.sandbox import PermissionProfile
from hey.domain.exceptions.sandbox import SandboxUnavailableError
from hey.domain.services.sandbox import ISandboxRunner
from hey.infrastructure.sandbox.runners import MacOSSandboxRunner, NoopSandboxRunner


def build_sandbox_runner(profile: PermissionProfile) -> ISandboxRunner:
    if profile.enforcement == "disabled":
        return NoopSandboxRunner()
    if profile.enforcement == "external":
        raise SandboxUnavailableError("external sandbox enforcement is not implemented")

    system = platform.system()
    if system == "Darwin":
        return MacOSSandboxRunner()
    raise SandboxUnavailableError(f"managed sandbox enforcement is not implemented for {system}")
