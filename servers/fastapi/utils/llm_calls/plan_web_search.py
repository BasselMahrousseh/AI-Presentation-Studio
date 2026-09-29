"""Decide whether a generation step searches the web, and with which query.

A deck's web_search_mode is "auto", "always" or "off" (see PresentationModel). "off" and an
unconfigured search provider never search. Otherwise one small model call writes the search
queries (one per subject) and, for "auto", also decides whether the topic needs facts the
model cannot reliably supply itself, mirroring the Workspace chatbot's Auto mode. "always"
uses the queries whatever the decision.
"""
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from llmai.shared import JSONSchemaResponse, ReasoningConfig, SystemMessage, UserMessage

from utils.llm_reasoning import get_reasoning_config
from utils.llm_utils import DisconnectChecker, generate_structured_with_schema_retries
from utils.web_search import (
    WebSearchMode,
    build_web_search_query,
    is_web_search_configured,
)

LOGGER = logging.getLogger(__name__)

# Enough to judge the topic; a Smart deck built from an outline passes the whole outline.
MAX_DECISION_CONTENT_CHARS = 4000

# Questions about AI models and vendors always search in Auto: models are released faster
# than any training cutoff, so the model's own knowledge of them is the least reliable.
_AI_VENDOR_PATTERN = re.compile(
    r"\b(anthropic|claude|(?:opus|sonnet|haiku)\s*\d|openai|gpt[-\s]?\d|chatgpt|gemini|"
    r"llama|mistral|grok|deepseek|qwen|cohere)\b",
    re.IGNORECASE,
)

WEB_SEARCH_DECISION_PROMPT = """
You decide whether a presentation needs a live web search before it is written, and if so
you write the search query.

# Decide
Set needsSearch to true when the presentation depends on facts you cannot reliably supply
from your own knowledge:
- anything recent, current, or that changes: news, releases, prices, market figures,
  rankings, statistics for a recent period, regulations, leadership, company results
- specific products, models, versions, companies, people, or events you do not recognise
  with confidence, or that may have appeared or changed after your training data
- comparisons or specifications of named products

Set needsSearch to false when the presentation can be written well from general knowledge
or from the provided content alone:
- timeless concepts, skills, processes, frameworks, training material, history
- internal plans, strategies, or pitches built from the user's own content
- content that already contains the facts the slides need

When unsure whether a named product, model, or figure is current, choose true.

# Queries
Always return 1 to 3 search-engine-style queries of at most 10 words each, even when
needsSearch is false:
- One query per distinct subject. For a comparison, one query per item compared; never
  one combined "A vs B" query.
- Use the full product or entity name so the query cannot match something else ("Claude
  Opus 5.5", not "Opus 5.5"; "iPhone 18 Pro", "e& Q2 2026 results"). Add the maker only
  when the name alone is still ambiguous; a bare company name pulls in its home page.
- Preserve names, versions, places and dates; add the year or a facet such as pricing,
  benchmarks, or results when it helps.
- No quotation marks, operators, or explanations.
""".strip()

WEB_SEARCH_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "needsSearch": {"type": "boolean"},
        "queries": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
            "minItems": 1,
            "maxItems": 3,
        },
    },
    "required": ["needsSearch", "queries"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class WebSearchPlan:
    search: bool
    queries: tuple[str, ...]
    # Why: "off", "not-configured", "always", "auto-model", "auto-ai-model-rule",
    # "auto-skip", "auto-decision-failed". Logged, and shown in tests.
    reason: str


def mentions_ai_model(text: str) -> bool:
    return bool(_AI_VENDOR_PATTERN.search(text or ""))


async def plan_web_search(
    client: Any,
    model: str,
    mode: WebSearchMode,
    content: str,
    instructions: Optional[str] = None,
    disconnect_checker: Optional[DisconnectChecker] = None,
) -> WebSearchPlan:
    if mode == "off":
        return WebSearchPlan(False, (), "off")
    if not is_web_search_configured():
        return WebSearchPlan(False, (), "not-configured")

    fallback_queries = (build_web_search_query(content, instructions)[:200],)
    started_at = time.monotonic()
    try:
        needs_search, queries = await _decide(
            client, model, content, instructions, disconnect_checker
        )
    except Exception:
        LOGGER.warning("Web search planning failed", exc_info=True)
        if mode == "always":
            return WebSearchPlan(True, fallback_queries, "always-fallback-query")
        # Auto must never block generation: without a decision, don't spend a search.
        return WebSearchPlan(False, (), "auto-decision-failed")

    if mode == "always":
        needs_search, reason = True, "always"
    elif needs_search:
        reason = "auto-model"
    elif mentions_ai_model(f"{content} {instructions or ''}"):
        needs_search, reason = True, "auto-ai-model-rule"
    else:
        reason = "auto-skip"
    LOGGER.info(
        "Web search plan: mode=%s search=%s reason=%s queries=%r duration_ms=%d",
        mode,
        needs_search,
        reason,
        queries,
        round((time.monotonic() - started_at) * 1000),
    )
    if not needs_search:
        return WebSearchPlan(False, (), reason)
    return WebSearchPlan(True, queries or fallback_queries, reason)


async def _decide(
    client: Any,
    model: str,
    content: str,
    instructions: Optional[str],
    disconnect_checker: Optional[DisconnectChecker],
) -> tuple[bool, tuple[str, ...]]:
    # A yes/no plus a few queries needs no reasoning: measured on six topics, the decisions
    # matched low effort exactly at 2.0s instead of 2.6s average.
    _, supports_thinking = get_reasoning_config(model, default_effort=None)
    reasoning = ReasoningConfig(enabled=False) if supports_thinking else None
    response = await generate_structured_with_schema_retries(
        client,
        model,
        messages=[
            SystemMessage(content=WEB_SEARCH_DECISION_PROMPT),
            UserMessage(
                content=(
                    f"TODAY'S DATE: {datetime.now().strftime('%Y-%m-%d')}\n\n"
                    f"CONTENT: {(content or '')[:MAX_DECISION_CONTENT_CHARS]}\n\n"
                    f"INSTRUCTIONS: {instructions or ''}"
                )
            ),
        ],
        response_format=JSONSchemaResponse(
            name="web_search_decision",
            json_schema=WEB_SEARCH_DECISION_SCHEMA,
            strict=False,
        ),
        json_schema=WEB_SEARCH_DECISION_SCHEMA,
        strict=False,
        validate_schema=True,
        validate_schema_max_loop_count=2,
        disconnect_checker=disconnect_checker,
        reasoning=reasoning,
    )
    queries = response.get("queries")
    normalized: list[str] = []
    for query in queries if isinstance(queries, list) else []:
        if isinstance(query, str) and (cleaned := " ".join(query.split())[:200]):
            if cleaned not in normalized:
                normalized.append(cleaned)
    return response.get("needsSearch") is True, tuple(normalized[:3])
