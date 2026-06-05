from hey.infrastructure.llm.codex import _MODEL_LIMITS as CODEX_LIMITS
from hey.infrastructure.llm.copilot import _MODEL_LIMITS as COPILOT_LIMITS
from hey.infrastructure.llm.litellm import _resolve_litellm_limits
from hey.infrastructure.llm.opencode import _MODEL_LIMITS as OPENCODE_LIMITS


def test_codex_default_model_has_limits() -> None:
    context, output = CODEX_LIMITS["o4-mini"]
    assert context > 0 and output > 0


def test_copilot_table_includes_gpt_4o() -> None:
    assert COPILOT_LIMITS["gpt-4o"][0] > 0


def test_opencode_table_includes_at_least_one_claude() -> None:
    assert any("claude" in name for name in OPENCODE_LIMITS)


def test_resolve_litellm_limits_exact_match() -> None:
    assert _resolve_litellm_limits("gpt-4o") == (128_000, 16_384)


def test_resolve_litellm_limits_strips_provider_prefix() -> None:
    assert _resolve_litellm_limits("anthropic/claude-sonnet-4-5") == (200_000, 64_000)


def test_resolve_litellm_limits_unknown_model_is_none() -> None:
    assert _resolve_litellm_limits("future-model-9000") == (None, None)
