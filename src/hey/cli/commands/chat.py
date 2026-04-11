import argparse
import asyncio
import json
import textwrap
from functools import partial
from types import TracebackType
from typing import Literal, assert_never

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from hey.domain.entities.llm import EmitLLMMessage, EmitLLMSignal, EmitToolResult, LLMMessage, ToolCallRecord
from hey.infrastructure.chat import InMemoryChatRepository
from hey.infrastructure.llm import get_litellm_spec
from hey.infrastructure.project import LocalProjectRepository
from hey.infrastructure.tool import BuiltinToolRepository
from hey.usecases.chat import AgentChatUseCase
from hey.usecases.project import ProjectUseCase


def _render_text(o: object, *, width: int | None = None, escape: bool = True) -> str:
    text = (repr(o)[1:-1] if escape else o) if isinstance(o, str) else repr(o)
    if width is not None:
        return textwrap.shorten(text, width=width, placeholder="…")
    return text


def _render_message(message: LLMMessage, *, width: int | None = None, escape: bool = True) -> str:
    return _render_text("".join(part["text"] for part in message["parts"]), width=width, escape=escape)


def _render_tool_call(record: ToolCallRecord, *, width: int | None = None) -> str:
    params = ", ".join(
        f"{key}={_render_text(json.dumps(val), width=10)}" for key, val in json.loads(record["args_json"]).items()
    )
    return _render_text(f"[bold]{record['name']}[/bold]: {params}", width=width)


def _tool_call_status_icon(status: Literal["success", "error", "denied"]) -> str:
    match status:
        case "success":
            return "[green]✔[/green]"
        case "error":
            return "[red]✘[/red]"
        case "denied":
            return "[yellow]⚠[/yellow]"
        case _:
            assert_never(status)


class ChatDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._markdown = Markdown("")
        self._pending: dict[str, tuple[ToolCallRecord, Columns]] = {}
        self._live = Live(self._renderable(), console=console, refresh_per_second=16)

    def _renderable(self) -> Group:
        return Group(self._markdown, *[line for _, line in self._pending.values()])

    def _refresh(self) -> None:
        self._live.update(self._renderable())

    def __enter__(self) -> "ChatDisplay":
        self._live.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._live.__exit__(exc_type, exc_val, exc_tb)

    def stop(self) -> None:
        self._live.stop()

    def start(self) -> None:
        self._live.start()
        self._refresh()

    def append_text_delta(self, delta: str) -> None:
        self._markdown = Markdown(self._markdown.markup + delta)
        self._refresh()

    def commit_message(self, message: LLMMessage) -> None:
        self._live.console.print(Markdown(_render_message(message, escape=False)))
        self._markdown = Markdown("")
        self._pending.clear()
        self._refresh()

    def add_pending_tool_call(self, record: ToolCallRecord) -> None:
        line = Columns([Spinner("dots"), Text.from_markup(_render_tool_call(record))])
        self._pending[record["id"]] = (record, line)
        self._refresh()

    def finish_tool_call(
        self, tool_call_id: str, result_text: str, status: Literal["success", "error", "denied"]
    ) -> None:
        entry = self._pending.pop(tool_call_id, None)
        if entry is None:
            return
        record, _ = entry
        self._live.console.print(f"{_tool_call_status_icon(status)} {_render_tool_call(record)}")
        self._live.console.print(f"    [dim]╰─ {result_text}[/dim]\n")
        self._refresh()


async def _ask_permission(display: ChatDisplay, console: Console, record: ToolCallRecord) -> Literal["allow", "deny"]:
    display.stop()
    try:
        while True:
            answer = await asyncio.to_thread(
                console.input,
                f"\n[yellow]Permission required:[/yellow] {_render_tool_call(record)}\nAllow this tool call? (y/n) ",
            )
            console.print()  # add a newline after input
            match answer.lower():
                case "y":
                    return "allow"
                case "n":
                    return "deny"
    finally:
        display.start()


async def _run_chat(prompt: str) -> None:
    project_use_case = ProjectUseCase(project_repository=LocalProjectRepository())
    project = project_use_case.get_project(path=".")

    console = Console()
    display = ChatDisplay(console)

    chat_use_case = AgentChatUseCase(
        permission=project.config.chat.permission,
        llm_spec=get_litellm_spec(model=project.config.chat.model, instructions=project.config.chat.instructions),
        chat_repository=InMemoryChatRepository(),
        tool_repository=BuiltinToolRepository(),
        ask_permission=partial(_ask_permission, display, console),
    )
    session = await chat_use_case.create_session(project_id=project.id)

    with display:
        async with chat_use_case.run(session_id=session.id, prompt=prompt) as response:
            async for event in response.events():
                match event:
                    case EmitLLMSignal(signal={"type": "text_delta", "delta": delta}):
                        display.append_text_delta(delta)
                    case EmitLLMMessage(message=message):
                        display.commit_message(message)
                        if message["role"] == "assistant":
                            for record in message["tool_calls"]:
                                display.add_pending_tool_call(record)
                    case EmitToolResult(message=message, status=status):
                        display.finish_tool_call(
                            message["tool_call_id"],
                            _render_message(message, width=60),
                            status,
                        )

    await response.collect()


def run(args: argparse.Namespace) -> None:
    asyncio.run(_run_chat(" ".join(args.prompt)))
