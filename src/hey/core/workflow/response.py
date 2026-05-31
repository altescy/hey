import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from .source import EventSource


class WorkflowResponse[EventT, StateT, ResultT]:
    def __init__(
        self,
        source: EventSource[EventT],
        coro: Callable[[], Coroutine[Any, Any, tuple[StateT, ResultT]]],
    ) -> None:
        self._source = source
        self._coro = coro
        self._task: asyncio.Task[tuple[StateT, ResultT]] | None = None

    def _ensure_started(self) -> asyncio.Task[tuple[StateT, ResultT]]:
        if self._task is None:
            self._task = asyncio.create_task(self._coro())
        return self._task

    def events(self, replay: int = 0) -> AsyncIterator[EventT]:
        async def _iter() -> AsyncIterator[EventT]:
            async with self._source.subscribe(replay=replay) as stream:
                self._ensure_started()
                async for e in stream:
                    yield e

        return _iter()

    async def collect(self) -> tuple[StateT, ResultT]:
        return await self._ensure_started()
