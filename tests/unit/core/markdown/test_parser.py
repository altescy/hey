from hey.core.markdown.parser import MarkdownParserState, parse_incremental


class TestParseIncremental:
    def test_heading_commits_when_next_content_in_tail(self) -> None:
        committed, buf = parse_incremental("# Hello\nsome text", None)
        assert committed == ["# Hello\n"]
        assert buf.text == "some text"

    def test_heading_with_blank_line(self) -> None:
        committed, buf = parse_incremental("# Hello\n\nsome text", None)
        assert committed == ["# Hello\n\n"]
        assert buf.text == "some text"

    def test_heading_pending_when_tail_empty(self) -> None:
        committed, buf = parse_incremental("# Hello\n", None)
        assert committed == []
        assert buf.text == "# Hello\n"
        assert buf.awaiting_separator is True

    def test_thematic_break_commits_when_next_content_in_tail(self) -> None:
        committed, buf = parse_incremental("---\nafter", None)
        assert committed == ["---\n"]
        assert buf.text == "after"

    def test_thematic_break_with_blank_line(self) -> None:
        committed, buf = parse_incremental("---\n\nafter", None)
        assert committed == ["---\n\n"]
        assert buf.text == "after"

    def test_consecutive_headings(self) -> None:
        committed, buf = parse_incremental("# H1\n## H2\ntext", None)
        assert committed == ["# H1\n", "## H2\n"]
        assert buf.text == "text"

    def test_paragraph_then_heading_with_tail(self) -> None:
        committed, buf = parse_incremental("some text\n# Title\nnext", None)
        assert committed == ["some text\n", "# Title\n"]
        assert buf.text == "next"

    def test_paragraph_then_heading_awaiting(self) -> None:
        committed, buf = parse_incremental("some text\n# Title\n", None)
        assert committed == ["some text\n"]
        assert buf.awaiting_separator is True

    def test_fenced_code_block_atomic(self) -> None:
        text = "```python\nprint('hello')\nprint('world')\n```\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["```python\nprint('hello')\nprint('world')\n```\n\n"]
        assert buf.text == "after"

    def test_fenced_code_not_split_on_blank_inside(self) -> None:
        text = "```\nline1\n\nline2\n```\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["```\nline1\n\nline2\n```\n\n"]
        assert buf.text == "after"

    def test_fenced_code_incremental(self) -> None:
        _, buf = parse_incremental("```\ncode\n", None)
        assert buf.in_fenced_code is True
        committed, buf = parse_incremental("more\n```\n\n", buf)
        assert committed == ["```\ncode\nmore\n```\n\n"]
        assert buf.in_fenced_code is False

    def test_tilde_fenced_code(self) -> None:
        text = "~~~\ncode\n\nmore\n~~~\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["~~~\ncode\n\nmore\n~~~\n\n"]
        assert buf.text == "after"

    def test_list_stays_together(self) -> None:
        text = "- item1\n- item2\n- item3\n\nnext"
        committed, buf = parse_incremental(text, None)
        assert committed == ["- item1\n- item2\n- item3\n\n"]
        assert buf.text == "next"

    def test_list_with_continuation(self) -> None:
        text = "- item1\n  continued\n- item2\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["- item1\n  continued\n- item2\n\n"]
        assert buf.text == "after"

    def test_ordered_list(self) -> None:
        text = "1. first\n2. second\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["1. first\n2. second\n\n"]
        assert buf.text == "after"

    def test_block_quote(self) -> None:
        text = "> line1\n> line2\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["> line1\n> line2\n\n"]
        assert buf.text == "after"

    def test_heading_then_list(self) -> None:
        text = "# Title\n- item\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["# Title\n", "- item\n\n"]
        assert buf.text == "after"

    def test_paragraph_commits_on_blank_line(self) -> None:
        text = "hello world\n\nnext"
        committed, buf = parse_incremental(text, None)
        assert committed == ["hello world\n\n"]
        assert buf.text == "next"

    def test_multi_line_paragraph(self) -> None:
        text = "line1\nline2\nline3\n\nnext"
        committed, buf = parse_incremental(text, None)
        assert committed == ["line1\nline2\nline3\n\n"]
        assert buf.text == "next"

    def test_paragraph_commits_on_heading(self) -> None:
        text = "paragraph\n# Heading\nnext"
        committed, buf = parse_incremental(text, None)
        assert committed == ["paragraph\n", "# Heading\n"]
        assert buf.text == "next"

    def test_incremental_char_by_char(self) -> None:
        text = "# Hi\nworld\n"
        buf: MarkdownParserState | None = None
        all_committed: list[str] = []
        for ch in text:
            committed, buf = parse_incremental(ch, buf)
            all_committed.extend(committed)
        assert all_committed == ["# Hi\n"]
        assert buf is not None
        assert buf.text == "world\n"

    def test_incremental_heading_commits_on_next_content(self) -> None:
        _, buf = parse_incremental("# Hi\n", None)
        assert buf.awaiting_separator is True
        committed, buf = parse_incremental("w", buf)
        assert committed == ["# Hi\n"]
        assert buf.text == "w"

    def test_incremental_heading_absorbs_blank(self) -> None:
        _, buf = parse_incremental("# Hi\n", None)
        committed, buf = parse_incremental("\n", buf)
        assert committed == ["# Hi\n\n"]

    def test_incremental_fenced_code_char_by_char(self) -> None:
        text = "```\ncode\n```\n\nafter"
        buf: MarkdownParserState | None = None
        all_committed: list[str] = []
        for ch in text:
            committed, buf = parse_incremental(ch, buf)
            all_committed.extend(committed)
        assert all_committed == ["```\ncode\n```\n\n"]
        assert buf is not None
        assert buf.text == "after"

    def test_empty_delta(self) -> None:
        _, buf = parse_incremental("hello", None)
        committed, buf = parse_incremental("", buf)
        assert committed == []
        assert buf.text == "hello"

    def test_text_property_includes_pending_and_tail(self) -> None:
        _, buf = parse_incremental("partial", None)
        assert buf.text == "partial"
        _, buf = parse_incremental(" line\nmore", buf)
        assert buf.text == "partial line\nmore"

    def test_multiple_blocks_in_one_delta(self) -> None:
        text = "# H1\n\nparagraph\n\n# H2\n\nend"
        committed, buf = parse_incremental(text, None)
        assert committed == ["# H1\n\n", "paragraph\n\n", "# H2\n\n"]
        assert buf.text == "end"

    def test_data_integrity(self) -> None:
        text = "# Title\n\nSome paragraph with **bold** and *italic*.\n\n```python\ndef hello():\n    print('world')\n```\n\n- item 1\n- item 2\n\n> quote\n\n---\n\nfinal"
        buf: MarkdownParserState | None = None
        all_committed: list[str] = []
        for ch in text:
            committed, buf = parse_incremental(ch, buf)
            all_committed.extend(committed)
        assert buf is not None
        reconstructed = "".join(all_committed) + buf.text
        assert reconstructed == text

    def test_fenced_code_without_trailing_blank(self) -> None:
        _, buf = parse_incremental("```\ncode\n```\n", None)
        assert buf.in_fenced_code is False
        assert buf.text == "```\ncode\n```\n"

    def test_table(self) -> None:
        text = "| a | b |\n| - | - |\n| 1 | 2 |\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["| a | b |\n| - | - |\n| 1 | 2 |\n\n"]
        assert buf.text == "after"

    def test_html_block(self) -> None:
        text = "<pre>\nhello\n</pre>\n\nafter"
        committed, buf = parse_incremental(text, None)
        assert committed == ["<pre>\nhello\n</pre>\n\n"]
        assert buf.text == "after"

    def test_finer_granularity_heading_paragraph_heading(self) -> None:
        text = "# Title\nparagraph text\n# Another\nnext"
        committed, buf = parse_incremental(text, None)
        assert len(committed) == 3
        assert committed[0] == "# Title\n"
        assert committed[1] == "paragraph text\n"
        assert committed[2] == "# Another\n"
        assert buf.text == "next"

    def test_finer_granularity_vs_old(self) -> None:
        text = "# Title\n- item1\n- item2\n\nnext"
        committed, buf = parse_incremental(text, None)
        assert committed == ["# Title\n", "- item1\n- item2\n\n"]
        assert buf.text == "next"

    def test_block_quote_then_paragraph(self) -> None:
        text = "> quote\n\nparagraph\n\n"
        committed, buf = parse_incremental(text, None)
        assert committed == ["> quote\n\n", "paragraph\n\n"]

    def test_data_integrity_large(self) -> None:
        text = (
            "# Heading 1\n\n"
            "Some paragraph.\n\n"
            "```python\ncode()\n```\n\n"
            "- list1\n- list2\n\n"
            "> blockquote\n\n"
            "---\n\n"
            "| a | b |\n| - | - |\n| 1 | 2 |\n\n"
            "final text"
        )
        committed, buf = parse_incremental(text, None)
        assert buf is not None
        reconstructed = "".join(committed) + buf.text
        assert reconstructed == text
