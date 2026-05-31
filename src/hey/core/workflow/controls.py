import dataclasses


@dataclasses.dataclass(frozen=True)
class Continue[EventT]:
    event: EventT


@dataclasses.dataclass(frozen=True)
class Stop[TerminalT]:
    result: TerminalT


type Control[EventT, TerminalT] = Continue[EventT] | Stop[TerminalT]
