from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from hey.core.workflow.response import WorkflowResponse
from hey.core.workflow.source import EventSource

from .protocols import Contextualizer, Engine, Reducer


def make_agent_runtime[StateT, QueryT, EventT, SignalT, BufferT](
    engine: Engine[QueryT, SignalT],
    reducer: Reducer[BufferT, SignalT, EventT],
    contextualizer: Contextualizer[QueryT, StateT],
) -> Callable[[StateT], AsyncIterator[EventT]]:
    async def _run(state: StateT) -> AsyncIterator[EventT]:
        buffer: BufferT | None = None
        query = contextualizer(state)
        async with engine(query) as stream:
            async for signal in stream:
                events, buffer = reducer(signal, buffer)
                for event in events:
                    yield event

    return _run


def run_agent_loop[StateT, EventT, CmdT, ResultT](
    state: StateT,
    *,
    runtime: Callable[[StateT], AsyncIterator[EventT]],
    update: Callable[[Sequence[EventT], StateT], tuple[StateT, Sequence[CmdT]]],
    interpret: Callable[[Sequence[CmdT], StateT], Awaitable[Sequence[EventT]]],
    is_done: Callable[[StateT], bool],
    finish: Callable[[StateT], ResultT],
) -> WorkflowResponse[EventT, StateT, ResultT]:
    source = EventSource[EventT]()

    async def _ro() -> tuple[StateT, ResultT]:
        current_state = state
        try:
            while not is_done(current_state):
                turn_events: list[EventT] = []
                async for event in runtime(current_state):
                    await source.publish(event)
                    turn_events.append(event)
                current_state, cmds = update(turn_events, current_state)
                while cmds:
                    results = await interpret(cmds, current_state)
                    for evt in results:
                        await source.publish(evt)
                    current_state, cmds = update(list(results), current_state)
            result = finish(current_state)
            await source.aclose()
            return current_state, result
        except BaseException as exc:
            await source.aclose(exception=exc)
            raise

    return WorkflowResponse(source, _ro)
