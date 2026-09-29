import asyncio

import pytest

from utils.llm_calls import plan_web_search as planner


def _plan(monkeypatch, mode, *, decision=None, configured=True, content="topic"):
    calls = {"decide": 0}

    async def fake_decide(*_args):
        calls["decide"] += 1
        if isinstance(decision, Exception):
            raise decision
        return decision

    monkeypatch.setattr(planner, "is_web_search_configured", lambda: configured)
    monkeypatch.setattr(planner, "_decide", fake_decide)
    plan = asyncio.run(
        planner.plan_web_search(object(), "model", mode, content, "instructions")
    )
    return plan, calls


def test_off_never_calls_the_model(monkeypatch):
    plan, calls = _plan(monkeypatch, "off")

    assert (plan.search, plan.reason) == (False, "off")
    assert calls["decide"] == 0


@pytest.mark.parametrize("mode", ["auto", "always"])
def test_unconfigured_provider_never_searches(monkeypatch, mode):
    plan, calls = _plan(monkeypatch, mode, configured=False)

    assert (plan.search, plan.reason) == (False, "not-configured")
    assert calls["decide"] == 0


def test_always_searches_even_when_the_model_would_skip(monkeypatch):
    plan, _ = _plan(monkeypatch, "always", decision=(False, ("latest market facts",)))

    assert (plan.search, plan.queries, plan.reason) == (True, ("latest market facts",), "always")


def test_always_falls_back_to_the_prompt_text_when_planning_fails(monkeypatch):
    plan, _ = _plan(
        monkeypatch, "always", decision=RuntimeError("no structured output"), content="current market"
    )

    assert plan.search is True
    assert plan.queries == ("current market instructions",)


def test_auto_follows_the_model_decision_with_one_query_per_subject(monkeypatch):
    plan, calls = _plan(
        monkeypatch,
        "auto",
        decision=(True, ("Apple iPhone 18 price UAE", "Samsung Galaxy S27 price UAE")),
    )

    assert plan.search is True
    assert plan.queries == ("Apple iPhone 18 price UAE", "Samsung Galaxy S27 price UAE")
    assert (plan.reason, calls["decide"]) == ("auto-model", 1)


def test_auto_skips_when_the_model_declines(monkeypatch):
    plan, _ = _plan(
        monkeypatch, "auto", decision=(False, ("onboarding tips",)), content="Onboarding tips for new hires"
    )

    assert (plan.search, plan.queries, plan.reason) == (False, (), "auto-skip")


def test_auto_always_searches_ai_model_topics(monkeypatch):
    plan, _ = _plan(
        monkeypatch,
        "auto",
        decision=(False, ("Anthropic Claude Opus 5.5", "OpenAI GPT-6 Astra")),
        content="add a slide about opus 5.5 vs gpt 6 astra",
    )

    assert plan.search is True
    assert plan.queries == ("Anthropic Claude Opus 5.5", "OpenAI GPT-6 Astra")
    assert plan.reason == "auto-ai-model-rule"


def test_auto_does_not_search_when_the_decision_fails(monkeypatch):
    plan, _ = _plan(monkeypatch, "auto", decision=RuntimeError("timeout"))

    assert (plan.search, plan.reason) == (False, "auto-decision-failed")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Opus 5.5 vs GPT-6 Astra", True),
        ("Claude for customer support", True),
        ("ChatGPT adoption at e&", True),
        ("A haiku workshop for poetry club", False),
        ("Beethoven's final opus", False),
        ("Quarterly sales review", False),
    ],
)
def test_mentions_ai_model(text, expected):
    assert planner.mentions_ai_model(text) is expected


@pytest.mark.parametrize(
    ("mode", "legacy_flag", "expected"),
    [
        (None, True, "always"),
        (None, False, "off"),
        (None, None, "off"),
        ("auto", False, "auto"),
        ("off", True, "off"),
    ],
)
def test_effective_web_search_mode_falls_back_to_the_legacy_flag(mode, legacy_flag, expected):
    from models.sql.presentation import PresentationModel

    presentation = PresentationModel(content="x", n_slides=1, language="en")
    presentation.web_search = legacy_flag
    presentation.web_search_mode = mode

    assert presentation.effective_web_search_mode == expected
