import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal


class EventSource[EventT]:
    _CLOSED: object = object()

    def __init__(
        self,
        max_buffer: int = 1000,
        slow_subscriber_policy: Literal["DROP", "ERROR"] = "DROP",
    ) -> None:
        self._max_buffer = max_buffer
        self._slow_subscriber_policy: Literal["DROP", "ERROR"] = slow_subscriber_policy
        self._queues: set[asyncio.Queue[EventT | object]] = set()
        self._history: deque[EventT] = deque(maxlen=max_buffer)
        self._lock = asyncio.Lock()
        self._closed = False
        self._exception: BaseException | None = None

    async def publish(self, event: EventT) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("EventSource is already closed")
            self._history.append(event)
            queues = list(self._queues)

            for q in queues:
                if q.full():
                    if self._slow_subscriber_policy == "ERROR":
                        raise RuntimeError(f"Subscriber queue is full (max_buffer={self._max_buffer})")
                    # DROP: skip delivery to this subscriber
                else:
                    q.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self, replay: int = 0) -> AsyncIterator[AsyncIterator[EventT]]:
        if replay > self._max_buffer:
            raise ValueError(f"replay={replay} exceeds max_buffer={self._max_buffer}")

        queue: asyncio.Queue[EventT | object] = asyncio.Queue(maxsize=self._max_buffer)

        async with self._lock:
            snapshot = list(self._history)[-replay:] if replay > 0 else []
            if self._closed:
                await queue.put(self._CLOSED)
            else:
                self._queues.add(queue)

        async def _iter() -> AsyncIterator[EventT]:
            for e in snapshot:
                yield e
            while True:
                item = await queue.get()
                if item is self._CLOSED:
                    break
                yield item  # type: ignore[misc]
            if self._exception is not None:
                raise self._exception

        try:
            yield _iter()
        finally:
            async with self._lock:
                self._queues.discard(queue)

    async def aclose(self, exception: BaseException | None = None) -> None:
        async with self._lock:
            self._closed = True
            self._exception = exception
            for q in self._queues:
                while True:
                    try:
                        q.put_nowait(self._CLOSED)
                        break
                    except asyncio.QueueFull:
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
