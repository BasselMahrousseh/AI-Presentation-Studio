import asyncio

import pytest

from utils.llm_calls import extract_atomic_facts


def test_extract_atomic_facts_skips_llm_call_for_short_text(monkeypatch):
    monkeypatch.setattr(
        extract_atomic_facts,
        "get_client",
        lambda **_kwargs: pytest.fail("LLM client should not be created"),
    )

    result = asyncio.run(
        extract_atomic_facts.extract_atomic_facts_from_text("Too short.", "source.pdf")
    )

    assert result == []


def test_extract_atomic_facts_skips_llm_call_for_empty_text(monkeypatch):
    monkeypatch.setattr(
        extract_atomic_facts,
        "get_client",
        lambda **_kwargs: pytest.fail("LLM client should not be created"),
    )

    result = asyncio.run(extract_atomic_facts.extract_atomic_facts_from_text("   ", "source.pdf"))

    assert result == []


def test_extract_atomic_facts_calls_llm_and_attaches_source_file(monkeypatch):
    captured = {}

    async def fake_generate_structured_with_schema_retries(
        _client, _model, *, messages, **_kwargs
    ):
        captured["messages"] = messages
        return {
            "facts": [
                {"fact_text": "UAE median download speed is 245 Mbps.", "topic": "download speed"},
                {"fact_text": "", "topic": "should be dropped"},
            ]
        }

    monkeypatch.setattr(extract_atomic_facts, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(extract_atomic_facts, "get_llm_config", lambda: {})
    monkeypatch.setattr(extract_atomic_facts, "get_model", lambda: "test-model")
    monkeypatch.setattr(
        extract_atomic_facts,
        "generate_structured_with_schema_retries",
        fake_generate_structured_with_schema_retries,
    )

    long_text = "A" * 250 + " UAE median download speed is 245 Mbps in Q2 2026."
    result = asyncio.run(
        extract_atomic_facts.extract_atomic_facts_from_text(long_text, "report.pdf")
    )

    assert len(result) == 1
    fact = result[0]
    assert fact.source_file == "report.pdf"
    assert fact.fact_text == "UAE median download speed is 245 Mbps."
    assert fact.topic == "download speed"
    assert fact.priority == "prose"
    assert long_text in captured["messages"][1].content


def test_extract_atomic_facts_raises_wrapped_error_on_llm_failure(monkeypatch):
    async def failing_call(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(extract_atomic_facts, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(extract_atomic_facts, "get_llm_config", lambda: {})
    monkeypatch.setattr(extract_atomic_facts, "get_model", lambda: "test-model")
    monkeypatch.setattr(
        extract_atomic_facts, "generate_structured_with_schema_retries", failing_call
    )

    long_text = "A" * 250
    with pytest.raises(Exception):
        asyncio.run(extract_atomic_facts.extract_atomic_facts_from_text(long_text, "report.pdf"))
