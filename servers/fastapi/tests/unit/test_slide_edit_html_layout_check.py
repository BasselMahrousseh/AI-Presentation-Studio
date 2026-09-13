"""Single-slide Smart HTML edits (POST /slide/edit-html) used to skip every
render-based layout-safety check that full-deck generation already applies -
an edit could silently reintroduce a canvas/footer overflow the initial
generation had already avoided. These tests pin the fix: the endpoint now
runs the edited HTML through the same _check_smart_slide_layout used during
generation, scaling slightly-too-large content to fit or rejecting a
violation too severe to scale, exactly mirroring generation-time behavior."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException

import api.v1.ppt.endpoints.slide as slide_module
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from tests.conftest import FakeAsyncSession


class _FakeMemoryService:
    async def retrieve_context(self, *_args, **_kwargs):
        return ""

    async def store_slide_edit(self, *_args, **_kwargs):
        return None


def _presentation(*, smart_template: str | None) -> PresentationModel:
    return PresentationModel(id=uuid.uuid4(), smart_template=smart_template)


def _slide(*, presentation_id: uuid.UUID, html_content: str) -> SlideModel:
    return SlideModel(
        id=uuid.uuid4(),
        presentation=presentation_id,
        layout_group="general",
        layout="content",
        index=0,
        html_content=html_content,
    )


def _session(presentation: PresentationModel, slide: SlideModel) -> FakeAsyncSession:
    return FakeAsyncSession(
        get_results={presentation.id: presentation, slide.id: slide}
    )


def test_edit_slide_html_scales_content_that_is_slightly_too_large(monkeypatch):
    presentation = _presentation(smart_template=None)
    slide = _slide(presentation_id=presentation.id, html_content="<section>old</section>")
    session = _session(presentation, slide)

    monkeypatch.setattr(
        slide_module,
        "get_edited_slide_html",
        lambda *_a, **_k: _async_result("<section>edited</section>"),
    )
    monkeypatch.setattr(slide_module, "MEM0_PRESENTATION_MEMORY_SERVICE", _FakeMemoryService())

    async def fake_check(_html, *, check_eand_footer):
        assert check_eand_footer is False
        return 0.9

    scaled_calls = []

    def fake_scale(html, scale):
        scaled_calls.append((html, scale))
        return f"{html}-scaled-{scale}"

    monkeypatch.setattr(slide_module, "_check_smart_slide_layout", fake_check)
    monkeypatch.setattr(slide_module, "_slide_html_scaled_to_fit", fake_scale)

    result = asyncio.run(
        slide_module.edit_slide_html(id=slide.id, prompt="make it bolder", sql_session=session)
    )

    assert scaled_calls == [("<section>edited</section>", 0.9)]
    assert result.html_content == "<section>edited</section>-scaled-0.9"
    assert session.commit_count == 1


def test_edit_slide_html_propagates_rejection_and_does_not_save(monkeypatch):
    presentation = _presentation(smart_template="eand")
    slide = _slide(presentation_id=presentation.id, html_content="<section>old</section>")
    session = _session(presentation, slide)

    monkeypatch.setattr(
        slide_module,
        "get_edited_slide_html",
        lambda *_a, **_k: _async_result("<section>broken</section>"),
    )
    monkeypatch.setattr(slide_module, "MEM0_PRESENTATION_MEMORY_SERVICE", _FakeMemoryService())

    async def fake_check(_html, *, check_eand_footer):
        assert check_eand_footer is True
        raise HTTPException(
            status_code=400,
            detail="content extends into the reserved e& footer area",
        )

    monkeypatch.setattr(slide_module, "_check_smart_slide_layout", fake_check)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            slide_module.edit_slide_html(
                id=slide.id, prompt="make it bolder", sql_session=session
            )
        )

    assert "reserved e& footer area" in excinfo.value.detail
    assert session.commit_count == 0
    assert slide.html_content == "<section>old</section>"


async def _async_result(value):
    return value
