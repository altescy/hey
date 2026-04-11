from collections.abc import AsyncIterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class Engine[QueryT, SignalT](Protocol):
    def __call__(self, query: QueryT) -> AbstractAsyncContextManager[AsyncIterable[SignalT]]: ...


@runtime_checkable
class Reducer[BufferT, SignalT, EventT](Protocol):
    def __call__(self, signal: SignalT, buffer: BufferT | None) -> tuple[Sequence[EventT], BufferT]: ...


@runtime_checkable
class Contextualizer[QueryT, StateT](Protocol):
    def __call__(self, state: StateT) -> QueryT: ...
