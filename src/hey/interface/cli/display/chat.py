import asyncio
import os
from enum import Enum, auto
from typing import Literal, TextIO

from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule
from rich.spinner import Spinner

from hey.core.markdown import MarkdownBuffer, reduce_markdown
from hey.domain.entities.llm import LLMMessage, ToolCallRecord, ToolResultMessage

from ._utils import BorderedWriter
from .console import get_console_width, render_llm_message, render_tool_call, tool_call_status_icon


class _Phase(Enum):
    IDLE = auto()
    WAITING = auto()
    STREAMING = auto()


class _BlockType(Enum):
    SESSION_START = auto()
    THINKING = auto()
    TEXT = auto()
    TOOL_RESULT = auto()
    PERMISSION = auto()


class ChatDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None
        self._phase = _Phase.IDLE
        self._thinking_writer: BorderedWriter | None = None
        self._md_buffer: MarkdownBuffer | None = None
        self._tool_calls: dict[str, ToolCallRecord] = {}
        self._previous_block_type: _BlockType | None = None
        self._permission_lock = asyncio.Lock()

    @property
    def has_pending_tool_calls(self) -> bool:
        return bool(self._tool_calls)

    @staticmethod
    def _get_tty_in() -> TextIO:
        if os.name == "nt":
            return open("CONIN$", "r", encoding="utf-8")
        return open("/dev/tty", "r", encoding="utf-8")

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

    def _apply_spacing(self, block_type: _BlockType) -> None:
        if self._previous_block_type is not None:
            if self._previous_block_type != block_type or block_type == _BlockType.PERMISSION:
                self._console.print()
        self._previous_block_type = block_type

    def _print(self, renderable: RenderableType, block_type: _BlockType) -> None:
        self._apply_spacing(block_type)
        self._console.print(renderable)

    def _streaming_renderable(self) -> RenderableType:
        pending = self._md_buffer.text if self._md_buffer else ""
        if pending:
            return Markdown(pending)
        return Group()

    def _ensure_thinking_writer(self) -> BorderedWriter:
        if self._thinking_writer is None:
            self._stop_live()
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

    def show_session_start(self, session_id: str) -> None:
        self._print(
            Rule(f"[dim]New session started  ·  Session {session_id}[/dim]", style="dim"), _BlockType.SESSION_START
        )

    def show_waiting(self) -> None:
        self._start_live(Columns([Spinner("dots")]))
        self._phase = _Phase.WAITING

    def show_compacting(self) -> None:
        self._stop_live()
        self._finish_thinking()
        self._start_live(Spinner("dots", text="[dim]Compacting context...[/dim]"))
        self._phase = _Phase.WAITING

    def hide_compacting(self) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE

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
                self._print(Markdown(block), _BlockType.TEXT)
            self._start_live(self._streaming_renderable())

        self._update_live(self._streaming_renderable())

    def commit_message(self, message: LLMMessage) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE
        self._finish_thinking()
        remaining = self._md_buffer.text if self._md_buffer else ""
        if remaining:
            self._print(Markdown(remaining), _BlockType.TEXT)
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
            self._print(f"{tool_call_status_icon(status)} {render_tool_call(record)}", _BlockType.TOOL_RESULT)
            if markdown:
                self._print(Markdown(markdown), _BlockType.TEXT)
            else:
                self._print(
                    f"  [dim]╰─ {render_llm_message(result, width=get_console_width(self._console) - 6)}[/dim]",
                    _BlockType.TOOL_RESULT,
                )

    def done(self) -> None:
        self._stop_live()
        self._phase = _Phase.IDLE

    async def _ainput(self, prompt: str, stream: TextIO) -> str | None:
        """Read a line from *stream* in a daemon thread so the event loop is not blocked.

        Returns ``None`` on EOF so the caller can distinguish it from an empty
        line (the user pressed Enter without typing anything).
        """
        import threading

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | None] = loop.create_future()

        def _read() -> None:
            try:
                result = self._console.input(prompt, stream=stream)
            except EOFError:
                loop.call_soon_threadsafe(future.set_result, None)
            except Exception as exc:
                loop.call_soon_threadsafe(future.set_exception, exc)
            else:
                loop.call_soon_threadsafe(future.set_result, result)

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        return await future

    async def ask_permission(self, record: ToolCallRecord) -> Literal["allow", "deny"]:
        self.done()
        async with self._permission_lock:
            self._apply_spacing(_BlockType.PERMISSION)
            tty_in = self._get_tty_in()
            writer = BorderedWriter(self._console, border="┃", border_style="yellow", padding=1)
            writer.write(
                f"[black bold on yellow] Permission required [/black bold on yellow] {render_tool_call(record)}"
            )
            writer.finish()
            while True:
                answer = await self._ainput(
                    f"{writer.prefix}Allow this tool call? (y/n) ",
                    tty_in,
                )
                if answer is None:
                    # EOF (e.g. Ctrl+D) – treat as deny.
                    return "deny"
                match answer.strip().lower():
                    case "y":
                        return "allow"
                    case "n":
                        return "deny"
