import asyncio
from enum import Enum, auto
from typing import Literal

from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner

from hey.core.markdown import MarkdownBuffer, reduce_markdown
from hey.domain.entities.llm import LLMMessage, ToolCallRecord, ToolResultMessage

from ._utils import BorderedWriter
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
        self._thinking_writer: BorderedWriter | None = None
        self._md_buffer: MarkdownBuffer | None = None
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
        pending = self._md_buffer.text if self._md_buffer else ""
        if pending:
            return Markdown(pending)
        return Group()

    def _ensure_thinking_writer(self) -> BorderedWriter:
        if self._thinking_writer is None:
            self._stop_live()
            self._console.print()
            self._thinking_writer = BorderedWriter(
                self._console,
                border="┃",
                style="dim",
                border_style="grey35",
                padding=1,
            )
            self._thinking_writer.write("[bold]thinking…[/bold]\n")
        return self._thinking_writer

    def _finish_thinking(self) -> None:
        if self._thinking_writer is not None:
            self._thinking_writer.finish()
            self._thinking_writer = None
            self._console.print()

    def show_waiting(self) -> None:
        self._start_live(Columns([Spinner("dots")]))
        self._phase = _Phase.WAITING

    def append_thinking_delta(self, delta: str) -> None:
        self._phase = _Phase.STREAMING
        writer = self._ensure_thinking_writer()
        writer.write(delta)

    def set_thinking_text(self, text: str) -> None:
        pass

    def append_text_delta(self, delta: str) -> None:
        if self._phase != _Phase.STREAMING:
            self._finish_thinking()
            self._start_live(self._streaming_renderable())
            self._phase = _Phase.STREAMING
        elif self._thinking_writer is not None:
            self._finish_thinking()
            self._start_live(self._streaming_renderable())

        committed, self._md_buffer = reduce_markdown(delta, self._md_buffer)
        if committed:
            self._stop_live()
            for block in committed:
                self._console.print(Markdown(block))
            self._start_live(self._streaming_renderable())

        self._update_live(self._streaming_renderable())

    def commit_message(self, message: LLMMessage) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE
        self._finish_thinking()
        remaining = self._md_buffer.text if self._md_buffer else ""
        if remaining:
            self._console.print(Markdown(remaining))
        self._md_buffer = None

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
                    f"  [dim]╰─ {render_llm_message(result, width=get_console_width(self._console) - 6)}[/dim]"
                )
                self._console.print()

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
        console.print()
        writer = BorderedWriter(console, border="┃", border_style="yellow", padding=1)
        writer.write(f"[black bold on yellow] Permission required [/black bold on yellow] {render_tool_call(record)}")
        writer.finish()
        while True:
            answer = await asyncio.to_thread(
                console.input,
                f"{writer.prefix}Allow this tool call? (y/n) ",
            )
            console.print()
            match answer.lower():
                case "y":
                    return "allow"
                case "n":
                    return "deny"
