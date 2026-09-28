import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

from llmai.shared import AssistantToolCall  # type: ignore[import-not-found]

from constants.presentation import MAX_NUMBER_OF_SLIDES, MAX_OUTLINE_CONTENT_WORDS
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from services.chat.memory_layer import PresentationChatMemoryLayer
from services.chat.tools import ChatTools
from utils.outline_limits import count_outline_words


def _run(coro):
    return asyncio.run(coro)


def _slide_ui():
    return {
        "id": "intro",
        "description": "Intro slide layout for chat ui testing.",
        "components": [
            {
                "id": "hero",
                "description": "Hero title component for testing.",
                "position": {"x": 0, "y": 0},
                "elements": [
                    {
                        "type": "text",
                        "decorative": False,
                        "name": "Title",
                        "position": {"x": 0, "y": 0},
                        "size": {"width": 100, "height": 40},
                        "max_length": 100,
                        "min_length": 1,
                        "runs": [
                            {
                                "text": "Old title",
                                "font": {"size": 20, "family": "Inter"},
                            }
                        ],
                    }
                ],
            },
            {
                "id": "body",
                "description": "Body list component for testing.",
                "position": {"x": 0, "y": 50},
                "elements": [
                    {
                        "type": "text-list",
                        "decorative": False,
                        "name": "Bullets",
                        "position": {"x": 0, "y": 0},
                        "size": {"width": 100, "height": 60},
                        "max_items": 6,
                        "min_items": 1,
                        "max_item_length": 80,
                        "min_item_length": 1,
                        "items": [[{"text": "First point"}]],
                    }
                ],
            },
        ],
    }


def _slide():
    return SlideModel(
        id=uuid.uuid4(),
        presentation=uuid.uuid4(),
        layout_group="custom-x",
        layout="intro",
        index=0,
        content={},
        properties=None,
        ui=_slide_ui(),
    )


class _FakeSlideSession:
    def __init__(self, slide: SlideModel):
        self.slide = slide
        self.presentation = PresentationModel(
            id=slide.presentation,
            version=PresentationVersion.V1_STANDARD,
            content="deck",
            n_slides=1,
            language="English",
            theme={
                "id": "test-theme",
                "name": "Test Theme",
                "data": {
                    "colors": {
                        "background_text": "#111827",
                        "stroke": "#E5E7EB",
                        "graph_0": "#123456",
                        "graph_1": "#234567",
                        "graph_2": "#345678",
                    }
                },
            },
        )
        self.commit_count = 0
        self.added: list = []

    async def scalar(self, *_args, **_kwargs):
        return self.slide

    async def get(self, model, key):
        if model is PresentationModel and key == self.presentation.id:
            return self.presentation
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _obj):
        return None


def _tools(slide: SlideModel) -> tuple[ChatTools, _FakeSlideSession]:
    session = _FakeSlideSession(slide)
    memory = PresentationChatMemoryLayer(session, slide.presentation)
    return ChatTools(memory), session


def _call(tools: ChatTools, name: str, arguments: dict):
    return _run(
        tools.execute_tool_call(
            AssistantToolCall(id="call_1", name=name, arguments=json.dumps(arguments))
        )
    )


def _set_reusable_table_layout(session: _FakeSlideSession):
    session.presentation.layout = {
        "name": "custom-test",
        "layouts": [
            {
                "id": "comparison",
                "description": "Comparison slide with reusable blocks.",
                "components": [
                    {
                        "id": "table_card",
                        "description": "Styled comparison table block.",
                        "position": {"x": 120, "y": 140},
                        "size": {"width": 900, "height": 360},
                        "elements": [{"type": "table", "name": "Comparison table"}],
                    },
                ],
            }
        ],
    }


def _slide_with_image():
    slide = _slide()
    slide.ui["components"].append(
        {
            "id": "visual",
            "description": "Hero image component.",
            "position": {"x": 0, "y": 120},
            "size": {"width": 100, "height": 80},
            "elements": [
                {
                    "type": "image",
                    "decorative": False,
                    "name": "Hero image",
                    "data": "/static/images/placeholder.jpg",
                    "is_icon": False,
                }
            ],
        }
    )
    return slide


def test_ui_tool_reports_non_ui_slide():
    slide = _slide()
    slide.ui = None
    tools, _ = _tools(slide)

    result = _call(tools, "getSlideAtIndex", {"index": 0, "includeFullContent": True})

    assert result["ok"] is True
    assert "ui_summary" not in result["result"]["slide"]


def _template_presentation(presentation_id: uuid.UUID) -> PresentationModel:
    return PresentationModel(
        id=presentation_id,
        version=PresentationVersion.V1_STANDARD,
        content="deck",
        n_slides=0,
        language="English",
        layout={
            "name": "custom-template",
            "template_id": "template",
            "layouts": [
                {
                    "id": "thanks",
                    "description": "Thank you slide layout for chat-created slides.",
                    "components": [
                        {
                            "id": "hero",
                            "description": "Hero title component for chat save tests.",
                            "position": {"x": 0, "y": 0},
                            "size": {"width": 100, "height": 40},
                            "elements": [
                                {
                                    "type": "text",
                                    "decorative": False,
                                    "name": "Title",
                                    "max_length": 100,
                                    "min_length": 1,
                                    "runs": [
                                        {
                                            "text": "Old title",
                                            "font": {"size": 20, "family": "Inter"},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )


class _FakeSaveSlideSession:
    def __init__(self, presentation: PresentationModel):
        self.presentation = presentation
        self.slides: list[SlideModel] = []
        self.added: list = []
        self.added_all: list = []
        self.commit_count = 0

    async def get(self, model, key):
        if model is PresentationModel and key == self.presentation.id:
            return self.presentation
        return None

    async def scalars(self, *_args, **_kwargs):
        return list(self.slides)

    async def scalar(self, *_args, **_kwargs):
        return self.slides[0] if self.slides else None

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, SlideModel) and obj not in self.slides:
            self.slides.append(obj)

    def add_all(self, values):
        self.added_all.extend(values)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _obj):
        return None

    async def delete(self, obj):
        if isinstance(obj, SlideModel) and obj in self.slides:
            self.slides.remove(obj)


def test_chat_add_outline_refuses_more_than_max_slides():
    presentation_id = uuid.uuid4()
    presentation = _template_presentation(presentation_id)
    presentation.outlines = {
        "slides": [
            {"content": f"## Slide {index}"}
            for index in range(MAX_NUMBER_OF_SLIDES)
        ]
    }
    session = _FakeSaveSlideSession(presentation)
    memory = PresentationChatMemoryLayer(session, presentation_id)

    result = _run(memory.add_outline(content="## Extra", index=None))

    assert result["saved"] is False
    assert result["slide_count"] == MAX_NUMBER_OF_SLIDES
    assert result["max_slide_count"] == MAX_NUMBER_OF_SLIDES
    assert session.commit_count == 0


def test_chat_update_outline_trims_content_to_word_limit():
    presentation_id = uuid.uuid4()
    presentation = _template_presentation(presentation_id)
    presentation.outlines = {"slides": [{"content": "## Existing"}]}
    session = _FakeSaveSlideSession(presentation)
    memory = PresentationChatMemoryLayer(session, presentation_id)
    content = " ".join(
        f"word{i}" for i in range(MAX_OUTLINE_CONTENT_WORDS + 4)
    )

    with patch(
        "services.chat.memory_layer.MEM0_PRESENTATION_MEMORY_SERVICE.store_generated_outlines",
        new=AsyncMock(),
    ):
        result = _run(memory.update_outline(index=0, content=content))

    assert result["saved"] is True
    saved_content = presentation.outlines["slides"][0]["content"]
    assert count_outline_words(saved_content) == MAX_OUTLINE_CONTENT_WORDS
    assert f"word{MAX_OUTLINE_CONTENT_WORDS - 1}" in saved_content
    assert f"word{MAX_OUTLINE_CONTENT_WORDS}" not in saved_content


