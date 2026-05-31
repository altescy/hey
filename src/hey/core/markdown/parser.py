from __future__ import annotations

import dataclasses
import enum
import re
from collections.abc import Sequence


class BlockKind(enum.Enum):
    ATX_HEADING = "atx_heading"
    THEMATIC_BREAK = "thematic_break"
    FENCED_CODE = "fenced_code"
    BLOCK_QUOTE = "block_quote"
    LIST = "list"
    TABLE = "table"
    HTML_BLOCK = "html_block"
    PARAGRAPH = "paragraph"


_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})")
_ATX_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:[-*_]\s*){3,}$")
_BLOCK_QUOTE_RE = re.compile(r"^ {0,3}> ?")
_LIST_MARKER_RE = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)]) ")
_TABLE_DELIMITER_RE = re.compile(r"^ *\|?[ :-]+\|[ :|+-]* *$")
_HTML_BLOCK_START_RE = re.compile(r"^ {0,3}<(?:pre|script|style|textarea|!--|!DOCTYPE|\?|!\[CDATA\[)", re.IGNORECASE)
_HTML_BLOCK_END_RE = re.compile(r"(?:</pre>|</script>|</style>|</textarea>|-->|\?>|\]\]>)", re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"^ *\|.*\| *$")


@dataclasses.dataclass(frozen=True)
class MarkdownParserState:
    pending_lines: tuple[str, ...] = ()
    current_kind: BlockKind | None = None
    fence_marker: str = ""
    fence_indent: int = 0
    in_html_block: bool = False
    table_has_delimiter: bool = False
    awaiting_separator: bool = False
    tail: str = ""

    @property
    def text(self) -> str:
        return "".join(self.pending_lines) + self.tail

    @property
    def in_fenced_code(self) -> bool:
        return self.current_kind == BlockKind.FENCED_CODE and not self.awaiting_separator


def _classify_line(line: str) -> BlockKind | None:
    stripped = line.strip()
    if not stripped:
        return None
    if _FENCE_RE.match(line):
        return BlockKind.FENCED_CODE
    if _ATX_HEADING_RE.match(line):
        return BlockKind.ATX_HEADING
    if _THEMATIC_BREAK_RE.match(stripped):
        return BlockKind.THEMATIC_BREAK
    if _HTML_BLOCK_START_RE.match(line):
        return BlockKind.HTML_BLOCK
    if _BLOCK_QUOTE_RE.match(line):
        return BlockKind.BLOCK_QUOTE
    if _LIST_MARKER_RE.match(line):
        return BlockKind.LIST
    if _TABLE_ROW_RE.match(line):
        return BlockKind.TABLE
    return BlockKind.PARAGRAPH


def _is_list_continuation(line: str) -> bool:
    if _LIST_MARKER_RE.match(line):
        return True
    return line.startswith("  ") or line.startswith("\t")


def parse_incremental(delta: str, state: MarkdownParserState | None) -> tuple[Sequence[str], MarkdownParserState]:
    state = state or MarkdownParserState()

    text = state.tail + delta

    raw_lines: list[str] = []
    last_end = 0
    for m in re.finditer(r"\n", text):
        raw_lines.append(text[last_end : m.end()])
        last_end = m.end()
    new_tail = text[last_end:]

    pending_lines = list(state.pending_lines)
    current_kind = state.current_kind
    fence_marker = state.fence_marker
    fence_indent = state.fence_indent
    in_html_block = state.in_html_block
    table_has_delimiter = state.table_has_delimiter
    awaiting_separator = state.awaiting_separator

    committed_texts: list[str] = []

    def _commit_pending() -> None:
        nonlocal pending_lines, current_kind, fence_marker, fence_indent
        nonlocal in_html_block, table_has_delimiter, awaiting_separator
        if pending_lines:
            committed_texts.append("".join(pending_lines))
        pending_lines = []
        current_kind = None
        fence_marker = ""
        fence_indent = 0
        in_html_block = False
        table_has_delimiter = False
        awaiting_separator = False

    def _begin_block(kind: BlockKind) -> None:
        nonlocal current_kind, awaiting_separator
        current_kind = kind
        awaiting_separator = False

    for raw_line in raw_lines:
        line_content = raw_line.rstrip("\n")
        line_kind = _classify_line(line_content)
        is_blank = line_kind is None

        if awaiting_separator:
            if is_blank:
                pending_lines.append(raw_line)
                _commit_pending()
                continue
            else:
                _commit_pending()

        if current_kind == BlockKind.FENCED_CODE:
            pending_lines.append(raw_line)
            if not is_blank:
                stripped = line_content.strip()
                ch = fence_marker[0]
                if stripped.startswith(ch) and len(stripped) >= len(fence_marker) and set(stripped) <= {ch}:
                    leading = len(line_content) - len(line_content.lstrip())
                    if leading <= fence_indent + 3:
                        awaiting_separator = True
            continue

        if in_html_block:
            pending_lines.append(raw_line)
            if _HTML_BLOCK_END_RE.search(line_content):
                awaiting_separator = True
            continue

        if is_blank:
            if current_kind is not None:
                pending_lines.append(raw_line)
                _commit_pending()
            else:
                pending_lines.append(raw_line)
                _commit_pending()
            continue

        assert line_kind is not None

        if line_kind == BlockKind.FENCED_CODE:
            if current_kind is not None:
                _commit_pending()
            m = _FENCE_RE.match(line_content)
            assert m is not None
            fence_indent = len(m.group(1))
            fence_marker = m.group(2)
            _begin_block(BlockKind.FENCED_CODE)
            pending_lines.append(raw_line)
            continue

        if line_kind == BlockKind.ATX_HEADING:
            if current_kind is not None:
                _commit_pending()
            pending_lines.append(raw_line)
            _begin_block(BlockKind.ATX_HEADING)
            awaiting_separator = True
            continue

        if line_kind == BlockKind.THEMATIC_BREAK:
            if current_kind is not None:
                _commit_pending()
            pending_lines.append(raw_line)
            _begin_block(BlockKind.THEMATIC_BREAK)
            awaiting_separator = True
            continue

        if line_kind == BlockKind.HTML_BLOCK:
            if current_kind is not None:
                _commit_pending()
            _begin_block(BlockKind.HTML_BLOCK)
            in_html_block = True
            pending_lines.append(raw_line)
            if _HTML_BLOCK_END_RE.search(line_content):
                awaiting_separator = True
            continue

        if line_kind == BlockKind.BLOCK_QUOTE:
            if current_kind == BlockKind.BLOCK_QUOTE:
                pending_lines.append(raw_line)
            else:
                if current_kind is not None:
                    _commit_pending()
                _begin_block(BlockKind.BLOCK_QUOTE)
                pending_lines.append(raw_line)
            continue

        if line_kind == BlockKind.LIST or (current_kind == BlockKind.LIST and _is_list_continuation(line_content)):
            if current_kind == BlockKind.LIST:
                pending_lines.append(raw_line)
            else:
                if current_kind is not None:
                    _commit_pending()
                _begin_block(BlockKind.LIST)
                pending_lines.append(raw_line)
            continue

        if line_kind == BlockKind.TABLE or current_kind == BlockKind.TABLE:
            if current_kind == BlockKind.TABLE:
                pending_lines.append(raw_line)
                if not table_has_delimiter and _TABLE_DELIMITER_RE.match(line_content):
                    table_has_delimiter = True
            else:
                if current_kind is not None:
                    _commit_pending()
                _begin_block(BlockKind.TABLE)
                table_has_delimiter = False
                pending_lines.append(raw_line)
            continue

        if current_kind == BlockKind.PARAGRAPH:
            pending_lines.append(raw_line)
            continue

        if current_kind is not None:
            _commit_pending()

        _begin_block(BlockKind.PARAGRAPH)
        pending_lines.append(raw_line)

    if awaiting_separator and new_tail.strip():
        _commit_pending()

    return committed_texts, MarkdownParserState(
        pending_lines=tuple(pending_lines),
        current_kind=current_kind,
        fence_marker=fence_marker,
        fence_indent=fence_indent,
        in_html_block=in_html_block,
        table_has_delimiter=table_has_delimiter,
        awaiting_separator=awaiting_separator,
        tail=new_tail,
    )
