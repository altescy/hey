from hey.core.markdown import reduce_markdown


class TestReduceMarkdown:
    def test_no_block_break(self) -> None:
        committed, buf = reduce_markdown("hello world", None)
        assert committed == []
        assert buf.text == "hello world"

    def test_single_block_break(self) -> None:
        committed, buf = reduce_markdown("first paragraph\n\nsecond", None)
        assert committed == ["first paragraph\n\n"]
        assert buf.text == "second"

    def test_multiple_block_breaks(self) -> None:
        committed, buf = reduce_markdown("aaa\n\nbbb\n\nccc", None)
        assert committed == ["aaa\n\n", "bbb\n\n"]
        assert buf.text == "ccc"

    def test_incremental_feed(self) -> None:
        _, buf = reduce_markdown("hello ", None)
        _, buf = reduce_markdown("world\n", buf)
        committed, buf = reduce_markdown("\nnext", buf)
        assert committed == ["hello world\n\n"]
        assert buf.text == "next"

    def test_fenced_code_block_not_split(self) -> None:
        text = "before\n\n```\nline1\n\nline2\n```\n\nafter"
        committed, buf = reduce_markdown(text, None)
        assert committed == ["before\n\n", "```\nline1\n\nline2\n```\n\n"]
        assert buf.text == "after"

    def test_fenced_code_block_incremental(self) -> None:
        _, buf = reduce_markdown("```\ncode\n", None)
        assert buf.in_fenced_code is True

        committed, buf = reduce_markdown("\nstill code\n```\n\n", buf)
        assert committed == ["```\ncode\n\nstill code\n```\n\n"]
        assert buf.in_fenced_code is False
        assert buf.text == ""

    def test_tilde_fenced_code(self) -> None:
        text = "~~~\ncode\n\nmore\n~~~\n\nafter"
        committed, buf = reduce_markdown(text, None)
        assert committed == ["~~~\ncode\n\nmore\n~~~\n\n"]
        assert buf.text == "after"

    def test_flush_remaining(self) -> None:
        _, buf = reduce_markdown("trailing text", None)
        assert buf.text == "trailing text"

    def test_empty_delta(self) -> None:
        _, buf = reduce_markdown("hello", None)
        committed, buf = reduce_markdown("", buf)
        assert committed == []
        assert buf.text == "hello"

    def test_heading_then_paragraph(self) -> None:
        committed, buf = reduce_markdown("# Title\n\nSome text", None)
        assert committed == ["# Title\n\n"]
        assert buf.text == "Some text"

    def test_list_items(self) -> None:
        text = "- item1\n- item2\n\nnext"
        committed, buf = reduce_markdown(text, None)
        assert committed == ["- item1\n- item2\n\n"]
        assert buf.text == "next"

    def test_triple_newline(self) -> None:
        committed, buf = reduce_markdown("a\n\n\nb", None)
        assert len(committed) >= 1
        remaining = "".join(committed) + buf.text
        assert remaining == "a\n\n\nb"
