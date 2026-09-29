import asyncio
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from llmai.openai.client import OpenAIClient  # type: ignore[import-not-found]
from llmai.shared.configs import OpenAIClientConfig  # type: ignore[import-not-found]
from llmai.shared.schema import get_schema_as_dict  # type: ignore[import-not-found]
from llmai.shared import AssistantToolCall, Tool  # type: ignore[import-not-found]

from enums.llm_provider import LLMProvider
from services.chat.llm_tools import build_chat_llm_tools
from services.chat.memory_layer import PresentationChatMemoryLayer
from services.chat import tools as chat_tools_module
from services.chat.tools import ChatTools
from utils.web_search import WebSearchResult


def _sample_function_tools() -> list[Tool]:
    return [
        Tool(
            name="getSlideAtIndex",
            description="Read a slide",
            input_schema={"type": "object", "properties": {}},
        )
    ]


@pytest.mark.parametrize(
    ("provider", "web_search_provider"),
    [
        (LLMProvider.AZURE, "auto"),
        (LLMProvider.AZURE, "native"),
        (LLMProvider.AZURE, "auto"),
        (LLMProvider.AZURE, "searxng"),
    ],
)
def test_build_chat_llm_tools_returns_only_function_tools(
    monkeypatch,
    provider,
    web_search_provider,
):
    monkeypatch.setenv("LLM", provider.value)
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", web_search_provider)
    function_tools = _sample_function_tools()

    tools = build_chat_llm_tools(function_tools)

    assert len(tools) == 1
    assert tools[0].name == "getSlideAtIndex"


@pytest.mark.parametrize(
    ("web_search_provider", "chat_mode", "expected"),
    [
        ("searxng", "auto", True),
        ("searxng", "always", True),
        ("searxng", "off", False),
        # No external provider configured: never offer the tool, whatever the mode.
        ("auto", "auto", False),
        ("native", "always", False),
    ],
)
@pytest.mark.parametrize("presentation_type", ["standard", "smart"])
def test_chat_offers_search_web_only_when_mode_and_provider_allow(
    monkeypatch,
    web_search_provider,
    chat_mode,
    expected,
    presentation_type,
):
    monkeypatch.setenv("LLM", LLMProvider.AZURE.value)
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", web_search_provider)
    monkeypatch.setenv("SEARXNG_BASE_URL", "http://127.0.0.1:8080")
    memory = Mock()
    memory.presentation_type = presentation_type

    tools = ChatTools(memory, web_search_mode=chat_mode).get_tool_definitions()

    assert any(tool.name == "searchWeb" for tool in tools) is expected


def test_search_web_tool_refuses_when_search_is_off(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "searxng")
    chat_tools = ChatTools(Mock(), web_search_mode="off")

    result = asyncio.run(
        chat_tools.execute_tool_call(
            AssistantToolCall(id="1", name="searchWeb", arguments='{"query": "x"}')
        )
    )

    assert result["ok"] is False


def test_search_web_tool_returns_titles_snippets_and_urls(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "searxng")

    async def fake_search_web(query):
        return [WebSearchResult("Opus 5.5 launch", "https://example.com/a", "Released in 2026.")]

    monkeypatch.setattr(chat_tools_module, "search_web", fake_search_web)
    chat_tools = ChatTools(Mock(), web_search_mode="auto")

    result = asyncio.run(
        chat_tools.execute_tool_call(
            AssistantToolCall(
                id="1", name="searchWeb", arguments='{"query": "Claude Opus 5.5"}'
            )
        )
    )

    assert result["ok"] is True
    assert result["result"]["count"] == 1
    assert result["result"]["results"][0] == {
        "title": "Opus 5.5 launch",
        "snippet": "Released in 2026.",
        "url": "https://example.com/a",
    }


def test_chat_tool_parse_args_repairs_fenced_jsonish_payload():
    assert ChatTools._parse_args(
        "```json\n{index: 0, includeFullContent: true}\n```"
    ) == {"index": 0, "includeFullContent": True}


def test_standard_chat_tools_are_outline_only():
    # "standard" presentations are the outline step's drafts; decks are always Smart.
    assert [tool.name for tool in ChatTools(Mock()).get_tool_definitions()] == [
        "getOutline",
        "addOutline",
        "updateOutline",
        "deleteOutline",
        "readSourceDocuments",
    ]


def test_get_outline_tool_takes_no_arguments_and_reads_the_store():
    memory = Mock()
    memory.get_outline = AsyncMock(return_value={"found": True, "slides": []})
    chat_tools = ChatTools(memory)

    result = asyncio.run(
        chat_tools.execute_tool_call(
            AssistantToolCall(id="1", name="getOutline", arguments="{}")
        )
    )

    assert result["ok"] is True
    assert result["result"] == {"found": True, "slides": []}
    memory.get_outline.assert_awaited_once_with()


def test_memory_get_outline_returns_zero_based_indexes_and_full_content():
    presentation = Mock(
        outlines={
            "slides": [
                {"content": "# Intro\n- Why this deck"},
                {"content": "# Results\n- Revenue grew 12%"},
            ]
        }
    )
    memory = PresentationChatMemoryLayer(_OutlineSession(presentation), uuid.uuid4())

    result = asyncio.run(memory.get_outline())

    assert result["found"] is True
    assert result["slide_count"] == 2
    assert result["slides"][1] == {
        "index": 1,
        "slide_number": 2,
        "content": "# Results\n- Revenue grew 12%",
    }


def test_memory_get_outline_reports_missing_presentation():
    memory = PresentationChatMemoryLayer(_OutlineSession(None), uuid.uuid4())

    assert asyncio.run(memory.get_outline())["found"] is False


class _OutlineSession:
    def __init__(self, presentation):
        self._presentation = presentation

    async def get(self, model, object_id):
        return self._presentation


def test_smart_chat_tools_edit_html_slides():
    memory = Mock()
    memory.presentation_type = "smart"
    assert [tool.name for tool in ChatTools(memory).get_tool_definitions()] == [
        "getSmartPresentationContext",
        "readSourceDocuments",
        "searchSlide",
        "getSlideAtIndex",
        "generateAssets",
        "saveSlide",
        "deleteSlide",
    ]


def test_chat_tools_emit_openai_strict_compatible_schemas(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "searxng")
    client = OpenAIClient(config=OpenAIClientConfig(api_key="test"))
    tools = ChatTools(Mock(), web_search_mode="auto").get_tool_definitions()
    assert any(tool.name == "searchWeb" for tool in tools)

    for tool in tools:
        schema = client._openai_schema(
            get_schema_as_dict(tool.input_schema, strict=tool.strict),
            strict=tool.strict,
        )
        _assert_openai_strict_schema(schema, tool.name)


def _assert_openai_strict_schema(node, tool_name: str):
    if isinstance(node, list):
        for item in node:
            _assert_openai_strict_schema(item, tool_name)
        return

    if not isinstance(node, dict):
        return

    if node.get("type") == "array":
        assert node.get("items") not in (None, {}), tool_name

    if node.get("type") == "object" and isinstance(node.get("properties"), dict):
        properties = set(node["properties"])
        assert set(node.get("required") or []) == properties, tool_name
        assert node.get("additionalProperties") is False, tool_name

    for variant in node.get("anyOf") or []:
        if isinstance(variant, dict):
            assert "type" in variant or "$ref" in variant, tool_name

    for value in node.values():
        _assert_openai_strict_schema(value, tool_name)
