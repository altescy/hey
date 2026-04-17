from collections.abc import Sequence

from hey.core.markdown.parser import MarkdownParserState, parse_incremental

MarkdownBuffer = MarkdownParserState


def reduce_markdown(delta: str, buffer: MarkdownBuffer | None) -> tuple[Sequence[str], MarkdownBuffer]:
    return parse_incremental(delta, buffer)
