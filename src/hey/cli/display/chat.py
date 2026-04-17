import asyncio
from enum import Enum, auto
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


class _Phase(Enum):
    IDLE = auto()
    WAITING = auto()
    STREAMING = auto()


class ChatDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None
        self._phase = _Phase.IDLE
        self._thinking = ""
        self._markdown = Markdown("")
        self._tool_calls: dict[str, ToolCallRecord] = {}

    @property
    def has_pending_tool_calls(self) -> bool:
        return bool(self._tool_calls)

    def _start_live(self, renderable: RenderableType) -> None:
        self._stop_live()
        self._live = Live(renderable, console=self._console, refresh_per_second=24, transient=True, screen=False)
        self._live.start()

    def _stop_live(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _update_live(self, renderable: RenderableType) -> None:
        if self._live is not None:
            self._live.update(renderable)

    def _streaming_renderable(self) -> RenderableType:
        renderables: list[RenderableType] = []
        if self._thinking:
            renderables.append(self._render_thinking_panel(self._thinking))
            renderables.append(Text(""))
        renderables.append(self._markdown)
        return Group(*renderables)

    def _render_thinking_panel(self, text: str) -> RenderableType:
        return Panel(
            Text(text, style="dim"),
            title="[dim]thinking[/dim]",
            border_style="grey35",
            style="on rgb(30,30,30)",
            padding=(0, 1),
        )

    def show_waiting(self) -> None:
        self._start_live(Columns([Spinner("dots")]))
        self._phase = _Phase.WAITING

    def append_thinking_delta(self, delta: str) -> None:
        if self._phase != _Phase.STREAMING:
            self._start_live(self._streaming_renderable())
            self._phase = _Phase.STREAMING
        self._thinking += delta
        self._update_live(self._streaming_renderable())

    def set_thinking_text(self, text: str) -> None:
        self._thinking = text
        if self._phase == _Phase.STREAMING:
            self._update_live(self._streaming_renderable())

    def append_text_delta(self, delta: str) -> None:
        if self._phase != _Phase.STREAMING:
            self._start_live(self._streaming_renderable())
            self._phase = _Phase.STREAMING
        self._markdown = Markdown(self._markdown.markup + delta)
        self._update_live(self._streaming_renderable())

    def commit_message(self, message: LLMMessage) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE
        if self._thinking:
            self._console.print()
            self._console.print(self._render_thinking_panel(self._thinking))
            self._console.print()
        self._console.print(Markdown(render_llm_message(message, escape=False)))
        self._thinking = ""
        self._markdown = Markdown("")

    def add_pending_tool_call(self, record: ToolCallRecord) -> None:
        self._tool_calls[record["id"]] = record

    def finish_tool_call(
        self,
        result: ToolResultMessage,
        status: Literal["success", "error", "denied"],
        markdown: str | None = None,
    ) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE

        record = self._tool_calls.pop(result["tool_call_id"], None)
        if record is not None:
            self._console.print(f"{tool_call_status_icon(status)} {render_tool_call(record)}")
            if markdown:
                self._console.print()
                self._console.print(Markdown(markdown))
                self._console.print()
            else:
                self._console.print(
                    f"    [dim]╰─ {render_llm_message(result, width=get_console_width(self._console) - 6)}[/dim]\n"
                )

    def done(self) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE


async def ask_permission(
    display: ChatDisplay,
    console: Console,
    lock: asyncio.Lock,
    record: ToolCallRecord,
) -> Literal["allow", "deny"]:
    display.done()
    async with lock:
        while True:
            answer = await asyncio.to_thread(
                console.input,
                f"[yellow]Permission required:[/yellow] {render_tool_call(record)}\nAllow this tool call? (y/n) ",
            )
            console.print()
            match answer.lower():
                case "y":
                    return "allow"
                case "n":
                    return "deny"
