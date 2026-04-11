import abc
from collections.abc import Sequence


class BaseWorkflowHandler[StateT, EventT, TerminalT](abc.ABC):
    @abc.abstractmethod
    def update(self, events: Sequence[EventT], state: StateT) -> StateT:
        raise NotImplementedError

    @abc.abstractmethod
    def finish(self, state: StateT) -> TerminalT:
        raise NotImplementedError
