from .codex import get_codex_spec
from .copilot import get_copilot_spec
from .litellm import get_litellm_spec
from .opencode import get_opencode_spec

__all__ = [
    "get_litellm_spec",
    "get_copilot_spec",
    "get_codex_spec",
    "get_opencode_spec",
]
