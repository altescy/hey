from __future__ import annotations

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from .console import get_console_width


class BorderedWriter:
    def __init__(
        self,
        console: Console,
        *,
        border: str = "┃",
        style: str = "",
        border_style: str = "",
        padding: int = 1,
    ) -> None:
        self._console = console
        self._border = border
        self._style = style
        self._border_style = border_style
        self._padding = padding
        self._buffer = ""
        self._finished = False

    @property
    def content_width(self) -> int:
        width = get_console_width(self._console)
        prefix_width = cell_len(self._border) + self._padding
        return max(width - prefix_width, 1)

    @property
    def prefix(self) -> str:
        pad = " " * self._padding
        if self._border_style:
            border = f"[{self._border_style}]{self._border}[/{self._border_style}]"
        else:
            border = self._border
        return f"{border}{pad}"

    def _print_line(self, text: str) -> None:
        formatted = f"{self.prefix}{text}"
        if self._style:
            self._console.print(formatted, style=self._style, highlight=False)
        else:
            self._console.print(formatted, highlight=False)

    def _print_wrapped(self, markup: str) -> None:
        t = Text.from_markup(markup)
        content_width = self.content_width
        if t.cell_len <= content_width:
            self._print_line(markup)
        else:
            wrapped = t.wrap(self._console, width=content_width, justify="left")
            for segment in wrapped:
                self._print_line(segment.markup.rstrip())

    def _flush_lines(self) -> None:
        while True:
            nl = self._buffer.find("\n")
            if nl == -1:
                t = Text.from_markup(self._buffer)
                if t.cell_len > self.content_width:
                    wrapped = t.wrap(self._console, width=self.content_width, justify="left")
                    for segment in wrapped[:-1]:
                        self._print_line(segment.markup.rstrip())
                    self._buffer = wrapped[-1].markup.rstrip() if wrapped else ""
                break
            line = self._buffer[:nl]
            self._buffer = self._buffer[nl + 1 :]
            self._print_wrapped(line)

    def write(self, delta: str) -> None:
        if self._finished:
            return
        self._buffer += delta
        self._flush_lines()

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._buffer:
            self._print_wrapped(self._buffer)
            self._buffer = ""
