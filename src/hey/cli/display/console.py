import json
import textwrap
from typing import Literal, assert_never

from rich.console import Console

from hey.domain.entities.llm import LLMMessage, ToolCallRecord


def get_console_width(console: Console) -> int:
    try:
        return console.size.width
    except Exception:
        return 80


def render_text(o: object, *, width: int | None = None, escape: bool = True) -> str:
    text = (repr(o)[1:-1] if escape else o) if isinstance(o, str) else repr(o)
    if width is not None:
        return textwrap.shorten(text, width=width, placeholder="…")
    return text


def render_llm_message(message: LLMMessage, *, width: int | None = None, escape: bool = True) -> str:
    return render_text("".join(part["text"] for part in message["parts"]), width=width, escape=escape)


def render_user_message_panel(message: LLMMessage, timestamp: str) -> object:
    from rich.panel import Panel
    from rich.text import Text

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
    params = ", ".join(f"{key}={render_text(json.dumps(val))}" for key, val in json.loads(record["args_json"]).items())
    return render_text(f"[bold]{record['name']}[/bold]: {params}", width=width)


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
