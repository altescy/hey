import asyncio
from types import TracebackType
from typing import Literal

from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from hey.domain.entities.llm import LLMMessage, ToolCallRecord, ToolResultMessage

from .console import get_console_width, render_llm_message, render_tool_call, tool_call_status_icon


class ChatDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._thinking = ""
        self._markdown = Markdown("")
        self._pending: dict[str, tuple[ToolCallRecord, Columns]] = {}
        self._deferred_output: list[RenderableType] = []
        self._live = Live(self._renderable(), console=console, refresh_per_second=16, transient=True, screen=False)
        self._stop_count = 0

    def _renderable(self) -> RenderableType:

        renderables: list[RenderableType] = []
        if self._thinking:
            renderables.append(self._render_thinking_panel(self._thinking))
            renderables.append(Text(""))
        renderables.append(self._markdown)
        renderables.extend(line for _, line in self._pending.values())
        return Group(*renderables)

    def _render_thinking_panel(self, text: str) -> RenderableType:
        return Panel(
            Text(text, style="dim"),
            title="[dim]thinking[/dim]",
            border_style="grey35",
            style="on rgb(30,30,30)",
            padding=(0, 1),
        )

    def _refresh(self) -> None:
        self._live.update(self._renderable())

    def _print(self, renderable: RenderableType) -> None:
        if self._stop_count > 0:
            self._deferred_output.append(renderable)
            return
        self._live.console.print(renderable)

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
        self._stop_count += 1
        if self._stop_count == 1:
            self._live.stop()

    def start(self) -> None:
        if self._stop_count <= 0:
            return
        self._stop_count -= 1
        if self._stop_count == 0:
            self._live.start()
            for renderable in self._deferred_output:
                self._live.console.print(renderable)
            self._deferred_output.clear()
            self._refresh()

    def append_text_delta(self, delta: str) -> None:
        self._markdown = Markdown(self._markdown.markup + delta)
        self._refresh()

    def append_thinking_delta(self, delta: str) -> None:
        self._thinking += delta
        self._refresh()

    def set_thinking_text(self, text: str) -> None:
        self._thinking = text
        self._refresh()

    def commit_message(self, message: LLMMessage) -> None:
        if self._thinking:
            self._print(Text(""))
            self._print(self._render_thinking_panel(self._thinking))
            self._print(Text(""))
        self._print(Markdown(render_llm_message(message, escape=False)))
        self._thinking = ""
        self._markdown = Markdown("")
        self._pending.clear()
        self._refresh()

    def add_pending_tool_call(self, record: ToolCallRecord) -> None:
        line = Columns([Spinner("dots"), Text.from_markup(render_tool_call(record))])
        self._pending[record["id"]] = (record, line)
        self._refresh()

    def finish_tool_call(
        self,
        result: ToolResultMessage,
        status: Literal["success", "error", "denied"],
        markdown: str | None = None,
    ) -> None:
        entry = self._pending.pop(result["tool_call_id"], None)
        if entry is None and self._pending:
            key = next(iter(self._pending))
            entry = self._pending.pop(key)
        if entry is None:
            return
        record, _ = entry
        self._print(f"{tool_call_status_icon(status)} {render_tool_call(record)}")
        if markdown:
            self._print(Text(""))
            self._print(Markdown(markdown))
            self._print(Text(""))
        else:
            self._print(f"    [dim]╰─ {render_llm_message(result, width=get_console_width(self._console) - 6)}[/dim]\n")
        self._refresh()


async def ask_permission(
    display: ChatDisplay,
    console: Console,
    lock: asyncio.Lock,
    record: ToolCallRecord,
) -> Literal["allow", "deny"]:
    display.stop()
    try:
        async with lock:
            while True:
                answer = await asyncio.to_thread(
                    console.input,
                    f"\n[yellow]Permission required:[/yellow] {render_tool_call(record)}\nAllow this tool call? (y/n) ",
                )
                console.print("\n")
                match answer.lower():
                    case "y":
                        return "allow"
                    case "n":
                        return "deny"
    finally:
        display.start()
