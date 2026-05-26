from hey.core.agent import InterpretInterrupted


class ToolCallDenied(Exception):
    """Tool call was denied by the agent's policy."""


class ToolExecutionInterrupted(InterpretInterrupted):
    """Tool execution was interrupted after (possibly partial) results were prepared."""
