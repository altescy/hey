import asyncio
from types import TracebackType
from typing import Literal

from rich.columns import Columns
from rich.console import Console, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from hey.domain.entities.llm import LLMMessage, ToolCallRecord, ToolResultMessage

from .console import get_console_width, render_llm_message, render_tool_call, tool_call_status_icon


class ChatDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._markdown = Markdown("")
        self._pending: dict[str, tuple[ToolCallRecord, Columns]] = {}
        self._live = Live(self._renderable(), console=console, refresh_per_second=16)
        self._stop_count = 0  # 参照カウント: > 0 のとき Live は停止中

    def _renderable(self) -> RenderableType:
        from rich.console import Group

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
        """停止リクエストを1つ積む。最初のリクエスト時だけ Live を停止する。"""
        self._stop_count += 1
        if self._stop_count == 1:
            self._live.stop()

    def start(self) -> None:
        """停止リクエストを1つ解放する。すべて解放されたとき Live を再開する。"""
        if self._stop_count <= 0:
            return
        self._stop_count -= 1
        if self._stop_count == 0:
            self._live.start()
            self._refresh()

    def append_text_delta(self, delta: str) -> None:
        self._markdown = Markdown(self._markdown.markup + delta)
        self._refresh()

    def commit_message(self, message: LLMMessage) -> None:
        self._live.console.print(Markdown(render_llm_message(message, escape=False)))
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
        if entry is None:
            return
        record, _ = entry
        self._live.console.print(f"{tool_call_status_icon(status)} {render_tool_call(record)}")
        if markdown:
            self._live.console.print()
            self._live.console.print(Markdown(markdown))
            self._live.console.print()
        else:
            self._live.console.print(
                f"    [dim]╰─ {render_llm_message(result, width=get_console_width(self._console) - 6)}[/dim]\n"
            )
        self._refresh()


async def ask_permission(
    display: ChatDisplay,
    console: Console,
    lock: asyncio.Lock,
    record: ToolCallRecord,
) -> Literal["allow", "deny"]:
    # Live をすぐに停止（参照カウントで管理されるため、複数同時でも1度だけ止まる）
    display.stop()
    try:
        async with lock:
            while True:
                answer = await asyncio.to_thread(
                    console.input,
                    f"\n[yellow]Permission required:[/yellow] {render_tool_call(record)}\nAllow this tool call? (y/n) ",
                )
                console.print()
                match answer.lower():
                    case "y":
                        return "allow"
                    case "n":
                        return "deny"
    finally:
        # 全ての確認が終わった時点で Live が再開される
        display.start()
