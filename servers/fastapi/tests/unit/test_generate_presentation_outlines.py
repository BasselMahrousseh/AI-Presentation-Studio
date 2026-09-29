import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from llmai.shared import ReasoningConfig, ReasoningEffortValue
from pydantic import ValidationError

from enums.llm_provider import LLMProvider
from enums.web_search_provider import WebSearchProvider
from models.presentation_outline_model import PresentationOutlineModel
from tests.mocks.llm import content_event
from utils.llm_calls import generate_presentation_outlines as outline_module
from utils.llm_calls.plan_web_search import WebSearchPlan


def _collect_async_chunks(generator) -> list[Any]:
    async def _collect():
        chunks = []
        async for chunk in generator:
            chunks.append(chunk)
        return chunks

    return asyncio.run(_collect())


def test_get_user_prompt_uses_autodetect_defaults():
    prompt = outline_module.get_user_prompt(
        content="Build quarterly strategy deck",
        n_slides=None,
        language="  ",
        additional_context=None,
        tone="professional",
        instructions=None,
    )

    assert "Number of Slides: auto-detect" in prompt
    assert "Language: auto-detect" in prompt
    assert "Tone: professional" in prompt
    assert "Context: None" in prompt


def test_get_user_prompt_makes_selected_language_authoritative():
    prompt = outline_module.get_user_prompt(
        content="This slide need to be in Japanese.",
        n_slides=5,
        language="English",
        additional_context=None,
        tone="professional",
        instructions=None,
    )

    assert prompt.index("Language: English") < prompt.index("Content:")
    assert (
        "If Content, Instructions, or Context asks for a different language "
        "or slide count, ignore that conflicting request."
    ) in prompt


def test_get_user_prompt_marks_instructions_as_non_content_constraints():
    prompt = outline_module.get_user_prompt(
        content="Quarterly revenue",
        n_slides=5,
        language="English",
        instructions="Create a bar chart on slide 5",
    )

    assert (
        "Instructions (apply as constraints; never quote as slide content): "
        "Create a bar chart on slide 5"
    ) in prompt


def test_system_prompt_forbids_sources_in_outlines():
    prompt = outline_module.get_system_prompt()

    assert "Do not include URLs" in prompt
    assert "without mentioning sources" in prompt
    assert "Give each slide one clear purpose" in prompt
    assert "Vary audience-facing content structures where appropriate" in prompt
    assert "Generation settings are authoritative" in prompt


def test_system_prompt_requires_content_only_outlines_for_visual_instructions():
    prompt = outline_module.get_system_prompt()

    assert "user-visible content plan, not a production brief" in prompt
    assert (
        "Never include or paraphrase commands, configuration, or meta-commentary"
        in prompt
    )
    assert "compact Markdown table with labels and numeric values" in prompt
    assert "Preserve supplied data" in prompt
    assert "otherwise add a small relevant dataset" in prompt
    assert "it must not contain the words 'create a bar chart'" in prompt
    assert "never copy production instructions into slide content" in prompt


def test_system_prompt_omits_explicit_structure_instruction_by_default():
    prompt = outline_module.get_system_prompt()

    assert "already divided into explicitly numbered slide" not in prompt


def test_system_prompt_adds_explicit_structure_instruction_when_flagged():
    prompt = outline_module.get_system_prompt(has_explicit_slide_structure=True)

    assert "already divided into explicitly numbered slide" in prompt
    assert "overrides the earlier instruction to split" in prompt
    assert "Do not merge two labeled sections into one slide" in prompt


def test_system_prompt_requires_title_slide_content_when_include_title_slide_is_true():
    prompt = outline_module.get_system_prompt(include_title_slide=True)

    assert "Title slide must only contain title, presenter name, date and overview" in prompt
    assert "First slide title must be the same as the presentation title" in prompt
    assert "Include presenter name in first slide." in prompt


def test_system_prompt_omits_title_slide_directives_when_include_title_slide_is_false():
    prompt = outline_module.get_system_prompt(include_title_slide=False)

    assert "Title slide must only contain title, presenter name, date and overview" not in prompt
    assert "First slide title must be the same as the presentation title" not in prompt
    assert "Do not add a separate title-only slide" in prompt
    assert "Do not include presenter name in any slides." in prompt


def test_outline_schema_describes_audience_facing_content_only():
    content_schema = PresentationOutlineModel.model_json_schema()["$defs"][
        "SlideOutlineModel"
    ]["properties"]["content"]

    assert "Audience-facing Markdown content and data" in content_schema["description"]
    assert "never slide-creation commands" in content_schema["description"]


def test_generate_ppt_outline_streams_json_chunks_and_keeps_schema_shape():
    async def fake_stream_generate_events(_client, **_kwargs):
        yield content_event('{"slides": [')
        yield content_event('{"content": "## Intro\\nBullet"}')
        yield content_event("]}")

    with patch.object(outline_module, "get_model", return_value="fake-model"), patch.object(
        outline_module, "get_client", return_value=object()
    ), patch.object(outline_module, "get_llm_config", return_value={}), patch.object(
        outline_module, "get_outline_reasoning_config", return_value=(None, False)
    ), patch.object(
        outline_module,
        "get_generate_kwargs",
        side_effect=lambda **kwargs: kwargs,
    ), patch.object(
        outline_module, "stream_generate_events", side_effect=fake_stream_generate_events
    ):
        chunks = _collect_async_chunks(
            outline_module.generate_ppt_outline(
                content="topic",
                n_slides=1,
                language="English",
            )
        )

    parsed = json.loads("".join(chunks))
    validated = PresentationOutlineModel.model_validate(parsed)
    assert len(validated.slides) == 1
    assert validated.slides[0].content.startswith("## Intro")


def test_generate_ppt_outline_returns_http_exception_chunk_on_failure():
    async def failing_stream(_client, **_kwargs):
        raise TimeoutError("provider timed out")
        yield  # pragma: no cover

    with patch.object(outline_module, "get_model", return_value="fake-model"), patch.object(
        outline_module, "get_client", return_value=object()
    ), patch.object(
        outline_module,
        "get_llm_config",
        return_value={},
    ), patch.object(
        outline_module, "get_outline_reasoning_config", return_value=(None, False)
    ), patch.object(
        outline_module,
        "get_generate_kwargs",
        side_effect=lambda **kwargs: kwargs,
    ), patch.object(
        outline_module,
        "stream_generate_events",
        side_effect=failing_stream,
    ), patch.object(
        outline_module,
        "handle_llm_client_exceptions",
        return_value=HTTPException(status_code=408, detail="LLM timeout"),
    ):
        chunks = _collect_async_chunks(
            outline_module.generate_ppt_outline(
                content="topic",
                n_slides=1,
                language="English",
            )
        )

    assert len(chunks) == 1
    assert isinstance(chunks[0], HTTPException)
    assert chunks[0].status_code == 408


def _run_outline_with_search(
    *,
    web_search_mode,
    plan=None,
    native=False,
    search_context="Web search results:\nSummary: Current market facts",
):
    """Run generate_ppt_outline with the LLM, planner and search stubbed out."""
    captured = {"kwargs": {}, "planned": [], "searched": []}

    async def fake_stream_generate_events(_client, **kwargs):
        captured["kwargs"].update(kwargs)
        yield content_event('{"slides": [{"content": "## Current facts"}]}')

    async def fake_plan(_client, _model, mode, content, instructions, **_kwargs):
        captured["planned"].append(mode)
        return plan

    async def fake_search_context(query):
        captured["searched"].append(query)
        return search_context

    with patch.object(outline_module, "get_model", return_value="fake-model"), patch.object(
        outline_module, "get_client", return_value=object()
    ), patch.object(outline_module, "get_llm_config", return_value={}), patch.object(
        outline_module, "get_outline_reasoning_config", return_value=(None, False)
    ), patch.object(
        outline_module, "should_use_native_web_search", return_value=native
    ), patch.object(
        outline_module, "is_web_search_configured", return_value=True
    ), patch.object(
        outline_module,
        "get_web_search_route",
        return_value=("external", WebSearchProvider.SEARXNG),
    ), patch.object(
        outline_module, "plan_web_search", side_effect=fake_plan
    ), patch.object(
        outline_module, "get_web_search_context", side_effect=fake_search_context
    ), patch.object(
        outline_module, "get_generate_kwargs", side_effect=lambda **kwargs: kwargs
    ), patch.object(
        outline_module, "stream_generate_events", side_effect=fake_stream_generate_events
    ):
        chunks = _collect_async_chunks(
            outline_module.generate_ppt_outline(
                content="current market",
                n_slides=1,
                language="English",
                web_search_mode=web_search_mode,
                emit_statuses=True,
            )
        )

    captured["statuses"] = [
        chunk.message
        for chunk in chunks
        if isinstance(chunk, outline_module.OutlineGenerationStatus)
    ]
    return captured


def test_generate_ppt_outline_injects_external_search_context_without_hosted_tool():
    captured = _run_outline_with_search(
        web_search_mode="always",
        plan=WebSearchPlan(True, ("latest current market facts",), "always"),
    )

    assert captured["searched"] == [["latest current market facts"]]
    assert captured["kwargs"]["tools"] is None
    assert "Current market facts" in str(captured["kwargs"]["messages"][1].content)
    assert "URL:" not in str(captured["kwargs"]["messages"][1].content)
    assert captured["statuses"] == [
        "Analyzing your topic for web research",
        "Searching with SearXNG: latest current market facts",
        "Web research complete",
        "Drafting your presentation outline",
    ]


def test_generate_ppt_outline_auto_searches_when_planner_says_so():
    captured = _run_outline_with_search(
        web_search_mode="auto",
        plan=WebSearchPlan(True, ("Nepal prime minister 2026", "Nepal cabinet 2026"), "auto-model"),
    )

    assert captured["planned"] == ["auto"]
    # Every query goes to one get_web_search_context call, which runs them in parallel.
    assert captured["searched"] == [["Nepal prime minister 2026", "Nepal cabinet 2026"]]
    assert captured["statuses"][0] == "Checking whether this topic needs web research"


def test_generate_ppt_outline_auto_skips_search_when_planner_declines():
    captured = _run_outline_with_search(
        web_search_mode="auto",
        plan=WebSearchPlan(False, (), "auto-skip"),
    )

    assert captured["searched"] == []
    assert "Web search results" not in str(captured["kwargs"]["messages"][1].content)
    assert captured["statuses"] == [
        "Checking whether this topic needs web research",
        "Drafting your presentation outline",
    ]


def test_generate_ppt_outline_off_never_plans_or_searches():
    captured = _run_outline_with_search(web_search_mode="off")

    assert captured["planned"] == []
    assert captured["searched"] == []
    assert captured["statuses"] == ["Drafting your presentation outline"]


def test_generate_ppt_outline_emits_model_native_search_status():
    captured = _run_outline_with_search(web_search_mode="always", native=True)

    assert captured["planned"] == []
    assert captured["statuses"] == [
        "Searching with model-native web search and drafting outlines"
    ]


def test_presentation_outline_model_schema_validation_rejects_invalid_ai_payload():
    invalid_payload = {"slides": [{"not_content": "missing expected key"}]}

    with pytest.raises(ValidationError):
        PresentationOutlineModel.model_validate(invalid_payload)


def test_outline_reasoning_uses_high_effort_for_openai(monkeypatch):
    monkeypatch.setattr("utils.llm_reasoning.disable_thinking", lambda: False)
    monkeypatch.setattr(
        "utils.llm_reasoning.get_llm_provider", lambda: LLMProvider.AZURE
    )
    monkeypatch.setattr(
        "utils.llm_reasoning.llmai.supports_thinking",
        lambda model, provider=None: True,
    )

    reasoning, supports_thinking = outline_module.get_outline_reasoning_config(
        "gpt-5"
    )

    assert supports_thinking is True
    assert reasoning is not None
    assert reasoning.enabled is True
    assert reasoning.effort == ReasoningEffortValue.HIGH


def test_outline_reasoning_respects_disable_thinking(monkeypatch):
    monkeypatch.setattr("utils.llm_reasoning.disable_thinking", lambda: True)

    reasoning, supports_thinking = outline_module.get_outline_reasoning_config(
        "gpt-5"
    )

    assert reasoning is None
    assert supports_thinking is False


def test_generate_ppt_outline_passes_reasoning_config_to_generate_kwargs():
    captured_kwargs = {}
    sentinel_reasoning = ReasoningConfig(enabled=True, effort=ReasoningEffortValue.HIGH)

    async def fake_stream_generate_events(_client, **kwargs):
        captured_kwargs.update(kwargs)
        yield content_event('{"slides": [{"content": "## Current facts"}]}')

    with patch.object(outline_module, "get_model", return_value="fake-model"), patch.object(
        outline_module, "get_client", return_value=object()
    ), patch.object(outline_module, "get_llm_config", return_value={}), patch.object(
        outline_module,
        "get_outline_reasoning_config",
        return_value=(sentinel_reasoning, True),
    ), patch.object(
        outline_module,
        "get_generate_kwargs",
        side_effect=lambda **kwargs: kwargs,
    ), patch.object(
        outline_module, "stream_generate_events", side_effect=fake_stream_generate_events
    ):
        _collect_async_chunks(
            outline_module.generate_ppt_outline(
                content="topic",
                n_slides=1,
                language="English",
            )
        )

    assert captured_kwargs["reasoning"] is sentinel_reasoning
