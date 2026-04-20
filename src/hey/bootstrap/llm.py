"""Resolve a ChatConfig.model name to the appropriate LLMSpec.

Model-name prefix conventions
------------------------------
``github-copilot/<model-id>``
    GitHub Copilot Chat Completions API.
    Authentication runs automatically via Device Flow on first use.

``codex/<model-id>``
    OpenAI Codex endpoint at chatgpt.com.
    Authentication runs automatically via PKCE/Device Flow on first use.

Anything else
    Delegated to litellm (OpenAI, Anthropic, Bedrock, Ollama, …).
"""

from __future__ import annotations

from hey.domain.entities.config import ChatConfig
from hey.domain.entities.llm import LLMSpec

_COPILOT_PREFIX = "github-copilot/"
_CODEX_PREFIX = "codex/"


def build_llm_spec(config: ChatConfig) -> LLMSpec:  # type: ignore[type-arg]
    model = config.model
    instructions = config.instructions

    if model.startswith(_COPILOT_PREFIX):
        from hey.infrastructure.llm.copilot import get_copilot_spec

        return get_copilot_spec(model=model[len(_COPILOT_PREFIX) :], instructions=instructions)

    if model.startswith(_CODEX_PREFIX):
        from hey.infrastructure.llm.codex import get_codex_spec

        return get_codex_spec(model=model[len(_CODEX_PREFIX) :], instructions=instructions)

    from hey.infrastructure.llm.litellm import get_litellm_spec

    return get_litellm_spec(model=model, instructions=instructions)
