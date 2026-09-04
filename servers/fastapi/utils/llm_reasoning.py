from __future__ import annotations

import llmai
from llmai.shared import ReasoningConfig, ReasoningEffortValue

from utils.llm_config import disable_thinking
from utils.llm_provider import get_llm_provider

# Providers confirmed to accept an explicit `effort` value on ReasoningConfig.
# Other providers may reject or ignore an explicit effort, so leave it unset
# for them and let the provider apply its own native default instead.
_EXPLICIT_EFFORT_PROVIDERS = {"openai", "azure"}


def get_reasoning_config(
    model: str, *, default_effort: ReasoningEffortValue | None
) -> tuple[ReasoningConfig | None, bool]:
    """Enable reasoning only when llmai knows the selected model supports it,
    and the admin `disable_thinking` kill-switch is off. `default_effort` is
    only sent to providers confirmed to accept an explicit effort value
    (openai/azure) - see get_smart_reasoning_config / get_outline_reasoning_config
    for which effort each generation path defaults to."""
    if disable_thinking():
        return None, False

    provider = get_llm_provider().value
    try:
        supports_thinking = llmai.supports_thinking(model, provider=provider) is True
    except Exception:
        supports_thinking = False
    if not supports_thinking:
        return None, False

    return (
        ReasoningConfig(
            enabled=True,
            effort=default_effort if provider in _EXPLICIT_EFFORT_PROVIDERS else None,
        ),
        True,
    )
