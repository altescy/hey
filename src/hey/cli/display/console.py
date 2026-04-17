import json
from typing import Literal, assert_never

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from hey.domain.entities.llm import LLMMessage, ToolCallRecord


def get_console_width(console: Console) -> int:
    try:
        return console.size.width
    except Exception:
        return 80


def render_text(o: object, *, width: int | None = None, escape: bool = True) -> str:
    text = (repr(o)[1:-1] if escape else o) if isinstance(o, str) else repr(o)
    if width is not None and width > 0:
        t = Text.from_markup(str(text))
        if t.cell_len > width:
            t.truncate(max(width - 1, 0), overflow="ellipsis", pad=False)
            t.append("…")
        return t.markup
    return str(text)


def render_llm_message(message: LLMMessage, *, width: int | None = None, escape: bool = True) -> str:
    return render_text("".join(part["text"] for part in message["parts"]), width=width, escape=escape)


def render_user_message_panel(message: LLMMessage, timestamp: str) -> object:
    content = "".join(part["text"] for part in message["parts"])
    header = Text(f"You  {timestamp}", style="dim")
    return Panel(
        content,
        title=header,
        title_align="left",
        border_style="blue",
        padding=(0, 1),
    )


def render_tool_call(record: ToolCallRecord, *, width: int | None = None) -> str:
    params = ", ".join(
        f"{key}={render_text(json.dumps(val, ensure_ascii=False))}"
        for key, val in json.loads(record["args_json"]).items()
    )
    return render_text(f"[bold]{record['name']}[/bold]: [dim]{params}[/dim]", width=width)


def tool_call_status_icon(status: Literal["success", "error", "denied"]) -> str:
    match status:
        case "success":
            return "[green]✔[/green]"
        case "error":
            return "[red]✘[/red]"
        case "denied":
            return "[yellow]⚠[/yellow]"
        case _:
            assert_never(status)
