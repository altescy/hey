from io import StringIO

from rich.console import Console

from hey.interface.cli.display._utils import BorderedWriter


def _make_console(width: int = 40) -> Console:
    return Console(file=StringIO(), width=width, highlight=False, color_system=None)


def _output(console: Console) -> str:
    f = console.file
    assert isinstance(f, StringIO)
    return f.getvalue()


class TestBorderedWriter:
    def test_single_line(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("hello\n")
        assert _output(console) == "┃ hello\n"

    def test_finish_flushes_remaining(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("hello")
        assert _output(console) == ""
        w.finish()
        assert _output(console) == "┃ hello\n"

    def test_multiple_lines(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("aaa\nbbb\n")
        assert _output(console) == "┃ aaa\n┃ bbb\n"

    def test_incremental_write(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("hel")
        assert _output(console) == ""
        w.write("lo\n")
        assert _output(console) == "┃ hello\n"

    def test_wrap_long_line(self) -> None:
        console = _make_console(width=10)
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("abcdefghij\n")
        lines = _output(console).splitlines(keepends=True)
        assert len(lines) == 2
        for line in lines:
            assert line.startswith("┃ ")

    def test_wrap_in_buffer(self) -> None:
        console = _make_console(width=10)
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("abcdefghijkl")
        out = _output(console)
        assert out.startswith("┃ ")
        assert out.count("\n") >= 1
        w.finish()
        full = _output(console)
        assert "abcdefghijkl" == "".join(line.removeprefix("┃ ").removeprefix("┃") for line in full.splitlines())

    def test_wide_characters(self) -> None:
        console = _make_console(width=10)
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("あいうえお\n")
        lines = _output(console).splitlines(keepends=True)
        assert len(lines) >= 2
        for line in lines:
            assert line.startswith("┃ ")

    def test_empty_write(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("")
        w.write("")
        assert _output(console) == ""
        w.finish()
        assert _output(console) == ""

    def test_empty_lines(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("a\n\nb\n")
        assert _output(console) == "┃ a\n┃ \n┃ b\n"

    def test_finish_idempotent(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.write("text")
        w.finish()
        out1 = _output(console)
        w.finish()
        assert _output(console) == out1

    def test_write_after_finish_ignored(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="┃", padding=1)
        w.finish()
        w.write("ignored")
        assert _output(console) == ""

    def test_custom_border(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border="│", padding=2)
        w.write("hi\n")
        assert _output(console) == "│  hi\n"

    def test_no_padding(self) -> None:
        console = _make_console()
        w = BorderedWriter(console, border=">", padding=0)
        w.write("test\n")
        assert _output(console) == ">test\n"

    def test_data_integrity_char_by_char(self) -> None:
        console = _make_console(width=15)
        w = BorderedWriter(console, border="┃", padding=1)
        text = "hello world this is a test\n"
        for ch in text:
            w.write(ch)
        output = _output(console)
        lines = output.splitlines()
        for line in lines:
            assert line.startswith("┃ ")
        content = " ".join(line.removeprefix("┃ ").removeprefix("┃").rstrip() for line in lines)
        assert content == text.rstrip("\n")
