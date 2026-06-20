import datetime

from rich.console import Group
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from hey.domain.entities.chat import ChatMessage
from hey.domain.entities.llm import LLMMessage
from hey.domain.repositories.chat import ChatSessionRetrievalResponse


def _message_text(message: LLMMessage) -> str:
    return "".join(part["text"] for part in message.get("parts", ()) if part["type"] == "text")


def _format_timestamp(dt: datetime.datetime) -> str:
    return dt.strftime("%m-%d %H:%M")


def _format_full_timestamp(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _truncate_text(text: str, width: int) -> str:
    if width <= 0:
        return text
    t = Text(text)
    if t.cell_len > width:
        t.truncate(max(width - 1, 0), overflow="ellipsis", pad=False)
        t.append("…")
    return t.plain


def render_session_table(response: ChatSessionRetrievalResponse) -> Table:
    table = Table(
        title="Chat sessions",
        expand=False,
        show_lines=False,
    )
    table.add_column("Session", justify="right", style="cyan")
    table.add_column("Created", style="dim")
    table.add_column("Updated", style="dim")
    table.add_column("Messages", justify="right")
    table.add_column("Preview")

    for item in response.results:
        session = item.session
        created = _format_full_timestamp(session.created_at)
        updated = _format_full_timestamp(session.updated_at)
        preview = _truncate_text(item.preview or "", 60)
        table.add_row(
            str(session.id),
            created,
            updated,
            str(item.message_count),
            preview,
        )

    return table


def _tool_call_result_text(messages: list[ChatMessage], tool_call_id: str) -> str:
    for chat_message in messages:
        msg = chat_message.message
        if msg.get("role") == "tool_result" and msg.get("tool_call_id") == tool_call_id:
            return _message_text(msg)
    return ""


def render_compact_messages(
    messages: list[ChatMessage],
    *,
    reverse: bool = False,
    width: int = 80,
) -> Group:
    lines: list[Text | Rule] = []
    ordered = list(reversed(messages)) if reverse else messages

    for chat_message in ordered:
        msg = chat_message.message
        ts = _format_timestamp(chat_message.created_at)

        if chat_message.kind == "summary":
            tail_start = chat_message.metadata.get("tail_start_message_id")
            tail_text = f" · tail #{tail_start}" if tail_start is not None else ""
            lines.append(Rule(f"[yellow]Compacted[/yellow] · [dim]{ts}{tail_text}[/dim]", style="yellow"))
            continue

        role = msg.get("role")
        if role == "user":
            text = _truncate_text(_message_text(msg), max(width - len(ts) - 6, 0))
            line = Text()
            line.append(f"{ts} ", style="dim")
            line.append("You: ", style="blue")
            line.append(text)
            lines.append(line)

        elif role == "assistant":
            text = _truncate_text(_message_text(msg), max(width - len(ts) - 12, 0))
            line = Text()
            line.append(f"{ts} ", style="dim")
            line.append("Assistant: ", style="green")
            line.append(text)
            lines.append(line)

            tool_calls = msg.get("tool_calls", ())
            for record in tool_calls:
                result_text = _tool_call_result_text(messages, record["id"])
                result_preview = _truncate_text(result_text, max(width - 30, 0))
                call_line = Text("  ")
                call_line.append("🔧 ", style="yellow")
                call_line.append(record["name"], style="bold")
                if result_preview:
                    call_line.append(f" → {result_preview}", style="dim")
                lines.append(call_line)

        elif role == "tool_result":
            text = _truncate_text(_message_text(msg), max(width - 8, 0))
            line = Text("  ")
            line.append("╰─ ", style="dim")
            line.append(text, style="dim")
            lines.append(line)

    return Group(*lines)


def _highlight_snippet(text: str, query: str, width: int) -> Text:
    lower_query = query.lower()
    index = text.lower().find(lower_query)
    if index < 0:
        snippet = _truncate_text(text, width)
        return Text(snippet)

    start = max(0, index - width // 4)
    end = min(len(text), start + width)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"

    result = Text()
    lower_snippet = snippet.lower()
    q_len = len(query)
    pos = 0
    while True:
        hit = lower_snippet.find(lower_query, pos)
        if hit < 0:
            result.append(snippet[pos:])
            break
        result.append(snippet[pos:hit])
        result.append(snippet[hit : hit + q_len], style="bold black on yellow")
        pos = hit + q_len
    return result


def render_search_results(
    messages: list[ChatMessage],
    query: str,
    *,
    width: int = 80,
) -> Table:
    table = Table(title=f'Search results for "{query}"', expand=False)
    table.add_column("Session", justify="right", style="cyan")
    table.add_column("Msg", justify="right", style="dim")
    table.add_column("Role", style="dim")
    table.add_column("Snippet")

    for chat_message in messages:
        msg = chat_message.message
        role = msg.get("role")
        if role == "tool_result":
            role_label = "tool"
        else:
            role_label = role or "?"
        text = _message_text(msg)
        snippet = _highlight_snippet(text, query, width)
        table.add_row(
            str(chat_message.session_id),
            str(chat_message.id),
            role_label,
            snippet,
        )

    return table
