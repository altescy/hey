from pathlib import Path

from hey.domain.entities.sandbox import SandboxExecRequest, SandboxExecResult
from hey.infrastructure.tool.builtins.bash import create_tool_spec


class FakeSandboxRunner:
    def __init__(self) -> None:
        self.requests: list[SandboxExecRequest] = []

    async def run(self, request: SandboxExecRequest) -> SandboxExecResult:
        self.requests.append(request)
        return SandboxExecResult(exit_code=0, stdout="ok", stderr="")


async def test_bash_executes_through_sandbox_runner(tmp_path) -> None:
    runner = FakeSandboxRunner()
    spec = create_tool_spec(sandbox_runner=runner)

    output = await spec.func("echo ok", workdir=str(tmp_path), timeout=5000)

    assert output == "ok"
    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.command[-2:] == ["-c", "echo ok"]
    assert request.cwd == Path(tmp_path)
    assert request.timeout_seconds == 5
    assert request.profile.enforcement == "disabled"


def test_bash_allows_safe_read_only_commands_by_default() -> None:
    spec = create_tool_spec()

    assert spec.permission["command.ls"] == "allow"
    assert spec.permission["command.ls *"] == "allow"
    assert spec.permission["command.pwd"] == "allow"
    assert spec.permission["command.rtk ls"] == "allow"
    assert spec.permission["command.rtk ls *"] == "allow"
    assert spec.permission["command.*"] == "ask"


async def test_render_markdown_uses_default_code_fence() -> None:
    spec = create_tool_spec()
    assert spec.render is not None

    markdown = await spec.render("hello", command="echo hello")

    assert markdown == "```\n$ echo hello\n\nhello\n```"


async def test_render_markdown_uses_longer_fence_when_output_contains_code_block() -> None:
    spec = create_tool_spec()
    assert spec.render is not None

    markdown = await spec.render("```python\nprint('hello')\n```", command="cat script.md")

    assert markdown == "````\n$ cat script.md\n\n```python\nprint('hello')\n```\n````"


async def test_render_markdown_accounts_for_backticks_in_command() -> None:
    spec = create_tool_spec()
    assert spec.render is not None

    markdown = await spec.render("ok", command="printf '````'")

    assert markdown == "`````\n$ printf '````'\n\nok\n`````"
