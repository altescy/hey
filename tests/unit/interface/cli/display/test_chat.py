from io import StringIO

from rich.console import Console

from hey.interface.cli.display.chat import ChatDisplay


class _CursorConsole(Console):
    def __init__(self) -> None:
        super().__init__(file=StringIO(), width=40, highlight=False, color_system=None)
        self.cursor_states: list[bool] = []

    def show_cursor(self, show: bool = True) -> bool:
        self.cursor_states.append(show)
        return True


class TestChatDisplay:
    def test_done_restores_cursor(self) -> None:
        console = _CursorConsole()
        display = ChatDisplay(console)

        display.done()

        assert console.cursor_states == [True]

    def test_done_restores_cursor_after_live_display(self) -> None:
        console = _CursorConsole()
        display = ChatDisplay(console)

        display.show_waiting()
        display.done()
        display.done()

        assert console.cursor_states[-2:] == [True, True]
