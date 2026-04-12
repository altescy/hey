"""Tests for hey.core.workflow.source (EventSource)."""

import asyncio

import pytest

from hey.core.workflow.source import EventSource


class TestEventSourcePublishAndSubscribe:
    @pytest.mark.asyncio
    async def test_subscriber_receives_published_events(self) -> None:
        source: EventSource[int] = EventSource()
        received: list[int] = []

        async with source.subscribe() as stream:
            await source.publish(1)
            await source.publish(2)
            await source.aclose()
            async for event in stream:
                received.append(event)

        assert received == [1, 2]

    @pytest.mark.asyncio
    async def test_multiple_subscribers_each_receive_all_events(self) -> None:
        source: EventSource[str] = EventSource()
        results: dict[str, list[str]] = {"a": [], "b": []}

        async def _consume(key: str) -> None:
            async with source.subscribe() as stream:
                async for event in stream:
                    results[key].append(event)

        async def _produce() -> None:
            await asyncio.sleep(0)
            await source.publish("x")
            await source.publish("y")
            await source.aclose()

        await asyncio.gather(_consume("a"), _consume("b"), _produce())
        assert results["a"] == ["x", "y"]
        assert results["b"] == ["x", "y"]

    @pytest.mark.asyncio
    async def test_replay_delivers_past_events(self) -> None:
        source: EventSource[int] = EventSource()
        await source.publish(10)
        await source.publish(20)

        received: list[int] = []
        async with source.subscribe(replay=2) as stream:
            await source.aclose()
            async for event in stream:
                received.append(event)

        assert received == [10, 20]

    @pytest.mark.asyncio
    async def test_replay_zero_skips_history(self) -> None:
        source: EventSource[int] = EventSource()
        await source.publish(10)

        received: list[int] = []
        async with source.subscribe(replay=0) as stream:
            await source.aclose()
            async for event in stream:
                received.append(event)

        assert received == []

    @pytest.mark.asyncio
    async def test_replay_exceeds_max_buffer_raises(self) -> None:
        source: EventSource[int] = EventSource(max_buffer=5)
        with pytest.raises(ValueError, match="replay=10 exceeds max_buffer=5"):
            async with source.subscribe(replay=10):
                pass


class TestEventSourceClose:
    @pytest.mark.asyncio
    async def test_publish_after_close_raises(self) -> None:
        source: EventSource[int] = EventSource()
        await source.aclose()
        with pytest.raises(RuntimeError, match="already closed"):
            await source.publish(1)

    @pytest.mark.asyncio
    async def test_subscribe_to_already_closed_source_ends_immediately(self) -> None:
        source: EventSource[int] = EventSource()
        await source.aclose()
        received: list[int] = []
        async with source.subscribe() as stream:
            async for event in stream:
                received.append(event)
        assert received == []

    @pytest.mark.asyncio
    async def test_aclose_with_exception_propagates_to_subscriber(self) -> None:
        source: EventSource[int] = EventSource()

        async def _produce() -> None:
            await asyncio.sleep(0)
            await source.aclose(exception=ValueError("upstream error"))

        with pytest.raises(ValueError, match="upstream error"):
            async with source.subscribe() as stream:
                await asyncio.gather(_produce(), return_exceptions=False)
                async for _ in stream:
                    pass

    @pytest.mark.asyncio
    async def test_subscriber_exits_cleanly_after_close(self) -> None:
        source: EventSource[str] = EventSource()
        collected: list[str] = []

        async def _consume() -> None:
            async with source.subscribe() as stream:
                async for event in stream:
                    collected.append(event)

        async def _produce() -> None:
            await source.publish("hello")
            await source.aclose()

        await asyncio.gather(_consume(), _produce())
        assert collected == ["hello"]


class TestEventSourceSlowSubscriber:
    @pytest.mark.asyncio
    async def test_drop_policy_does_not_raise_on_full_queue(self) -> None:
        source: EventSource[int] = EventSource(max_buffer=2, slow_subscriber_policy="DROP")
        async with source.subscribe():
            # Overfill the queue — should not raise with DROP policy
            for i in range(10):
                await source.publish(i)

    @pytest.mark.asyncio
    async def test_error_policy_raises_on_full_queue(self) -> None:
        source: EventSource[int] = EventSource(max_buffer=1, slow_subscriber_policy="ERROR")
        with pytest.raises(RuntimeError, match="queue is full"):
            async with source.subscribe():
                # First publish fills the queue (size 1), second should raise
                await source.publish(1)
                await source.publish(2)
