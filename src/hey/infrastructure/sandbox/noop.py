from __future__ import annotations

import asyncio

from hey.domain.entities.sandbox import SandboxExecRequest, SandboxExecResult


class NoopSandboxRunner:
    async def run(self, request: SandboxExecRequest) -> SandboxExecResult:
        process = await asyncio.create_subprocess_exec(
            *request.command,
            cwd=request.cwd,
            env=dict(request.env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=request.timeout_seconds)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            return SandboxExecResult(
                exit_code=-1,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                timed_out=True,
            )

        return SandboxExecResult(
            exit_code=process.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )
