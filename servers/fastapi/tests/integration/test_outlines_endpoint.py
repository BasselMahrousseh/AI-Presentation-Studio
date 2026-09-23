import asyncio
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.v1.ppt.endpoints import outlines as outlines_endpoint
from constants.presentation import MAX_NUMBER_OF_SLIDES
from models.extraction_quality import VisualExtractability, VisualQualityFlag
from models.sql.presentation import PresentationModel, PresentationVersion
from tests.conftest import FakeAsyncSession
from utils.outline_utils import get_no_of_outlines_to_generate_for_n_slides


class FakeRequestWithDisconnect:
    def __init__(self):
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}
        self.state = SimpleNamespace()

    async def is_disconnected(self) -> bool:
        return False


def _run(coro):
    return asyncio.run(coro)


def _explicit_structure_content(n: int) -> str:
    return "\n".join(
        f"Slide {i}: Section {i}\nSome body text about section {i}."
        for i in range(1, n + 1)
    )


def _make_presentation(content: str, n_slides: int = 0, **overrides) -> PresentationModel:
    now = datetime.now()
    presentation_id = overrides.pop("id", uuid.uuid4())
    fields = dict(
        id=presentation_id,
        version=PresentationVersion.V2_STANDARD,
        content=content,
        n_slides=n_slides,
        language="English",
        file_paths=None,
        created_at=now,
        updated_at=now,
    )
    fields.update(overrides)
    return PresentationModel(**fields)


def make_fake_generate_ppt_outline(calls: list):
    async def fake_generate_ppt_outline(content, n_slides_to_generate, *args, **kwargs):
        calls.append(n_slides_to_generate)
        slide_count = n_slides_to_generate if n_slides_to_generate is not None else 3
        slides = [{"content": f"## Slide {i + 1}"} for i in range(slide_count)]
        yield json.dumps({"slides": slides})

    return fake_generate_ppt_outline


async def _drain_and_get_presentation_payload(response) -> dict:
    payload = None
    async for chunk in response.body_iterator:
        for block in chunk.split("\n\n"):
            if not block.startswith("event: response\ndata: "):
                continue
            data = json.loads(block[len("event: response\ndata: "):])
            if data.get("type") == "complete" and "presentation" in data:
                payload = data["presentation"]
    assert payload is not None, "stream never completed"
    return payload


async def _drain_and_collect_events(response) -> list[dict]:
    events = []
    async for chunk in response.body_iterator:
        for block in chunk.split("\n\n"):
            if not block.startswith("event: response\ndata: "):
                continue
            events.append(json.loads(block[len("event: response\ndata: "):]))
    return events


def _stream_outlines_patches(calls: list):
    return (
        patch.object(
            outlines_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE,
            "store_generation_context",
            new=AsyncMock(),
        ),
        patch.object(
            outlines_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE,
            "store_generated_outlines",
            new=AsyncMock(),
        ),
        patch.object(
            outlines_endpoint,
            "generate_ppt_outline",
            side_effect=make_fake_generate_ppt_outline(calls),
        ),
    )


async def _stream_once_response(presentation_id: uuid.UUID, session: FakeAsyncSession):
    return await outlines_endpoint.stream_outlines(
        id=presentation_id,
        request=FakeRequestWithDisconnect(),
        sql_session=session,
    )


async def _stream_once(presentation_id: uuid.UUID, session: FakeAsyncSession) -> dict:
    response = await _stream_once_response(presentation_id, session)
    return await _drain_and_get_presentation_payload(response)


def test_stream_outlines_has_explicit_slide_structure_is_idempotent_across_repeated_calls():
    """Regression test for the has_explicit_slide_structure idempotency bug
    (BUG_REPORT_has_explicit_slide_structure_idempotency.md): the first call
    to GET /outlines/stream/{id} for content with clean "Slide N:" markers
    must detect has_explicit_slide_structure=true, and every subsequent call
    for the same id must report the same result - not silently flip to
    false because a prior call's own success path backfilled n_slides.
    """
    presentation_id = uuid.uuid4()
    presentation = _make_presentation(_explicit_structure_content(2), id=presentation_id)
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3:
        results = [_run(_stream_once(presentation_id, session)) for _ in range(4)]

    for i, payload in enumerate(results):
        assert payload["has_explicit_slide_structure"] is True, (
            f"call {i + 1} returned has_explicit_slide_structure="
            f"{payload['has_explicit_slide_structure']!r}"
        )


def test_stream_outlines_without_explicit_structure_stays_false_and_stable_on_repeat_calls():
    """Content with no "Slide N:" markers was never part of the bug (it
    already reported False on every call, first or repeat) - this pins that
    behavior stays byte-identical after the fix.
    """
    presentation_id = uuid.uuid4()
    presentation = _make_presentation(
        "Write a presentation about renewable energy trends.",
        id=presentation_id,
    )
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3:
        results = [_run(_stream_once(presentation_id, session)) for _ in range(3)]

    assert [p["has_explicit_slide_structure"] for p in results] == [False, False, False]
    # n_slides_to_generate on the 2nd and 3rd calls must be stable relative
    # to each other - both computed from the by-then-backfilled n_slides,
    # pre-existing behavior this fix does not touch.
    assert calls[1] == calls[2]


def test_stream_outlines_explicit_n_slides_at_creation_wins_on_every_call():
    """A user-provided n_slides at creation time is existing, deliberate
    product behavior that must keep winning over content detection on the
    first call, and must stay False (detection never governs) on every
    repeat call too.
    """
    presentation_id = uuid.uuid4()
    presentation = _make_presentation(
        _explicit_structure_content(2), n_slides=5, id=presentation_id
    )
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3:
        results = [_run(_stream_once(presentation_id, session)) for _ in range(3)]

    assert [p["has_explicit_slide_structure"] for p in results] == [False, False, False]


@pytest.mark.parametrize("marker_count", [2, 4, 8])
def test_stream_outlines_detected_slide_target_is_stable_across_calls(marker_count):
    presentation_id = uuid.uuid4()
    presentation = _make_presentation(
        _explicit_structure_content(marker_count), id=presentation_id
    )
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3:
        first = _run(_stream_once(presentation_id, session))
        second = _run(_stream_once(presentation_id, session))

    expected = get_no_of_outlines_to_generate_for_n_slides(
        n_slides=min(marker_count, MAX_NUMBER_OF_SLIDES),
        toc=presentation.include_table_of_contents,
        title_slide=presentation.include_title_slide,
    )
    assert calls[0] == expected
    assert calls[1] == expected
    assert first["has_explicit_slide_structure"] is True
    assert second["has_explicit_slide_structure"] is True


def _fake_documents_loader(quality_flags: list[VisualQualityFlag]):
    class FakeDocumentsLoader:
        def __init__(self, *args, **kwargs):
            self.documents = ["extracted document text"]
            self.structured_pptx_data = [None]
            self.quality_flags = quality_flags

        async def load_documents(self, *args, **kwargs):
            return None

    return FakeDocumentsLoader


def test_stream_outlines_emits_and_persists_quality_flag_groups():
    presentation_id = uuid.uuid4()
    presentation = _make_presentation(
        "Combine these two reports.",
        file_paths=["/tmp/a.pdf", "/tmp/b.pptx"],
        id=presentation_id,
    )
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []
    flags = [
        VisualQualityFlag(
            source_file="a.pdf",
            location="Page 1",
            visual_kind="image",
            status=VisualExtractability.IMAGE_ONLY,
            detail="detail",
            recommendation="recommendation",
        )
    ]

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3, patch.object(
        outlines_endpoint, "DocumentsLoader", _fake_documents_loader(flags)
    ):
        response = _run(_stream_once_response(presentation_id, session))
        events = _run(_drain_and_collect_events(response))

    quality_flag_events = [event for event in events if event.get("type") == "quality_flags"]
    assert len(quality_flag_events) == 1
    groups = quality_flag_events[0]["groups"]
    assert len(groups) == 1
    assert groups[0]["group_key"] == "a.pdf::image_only"
    assert groups[0]["acknowledged"] is False

    assert presentation.source_quality_flags == [flags[0].model_dump(mode="json")]


def test_stream_outlines_reflects_previously_acknowledged_groups():
    presentation_id = uuid.uuid4()
    presentation = _make_presentation(
        "Combine these two reports.",
        file_paths=["/tmp/a.pdf"],
        acknowledged_quality_flag_groups=["a.pdf::image_only"],
        id=presentation_id,
    )
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []
    flags = [
        VisualQualityFlag(
            source_file="a.pdf",
            location="Page 1",
            visual_kind="image",
            status=VisualExtractability.IMAGE_ONLY,
            detail="detail",
            recommendation="recommendation",
        )
    ]

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3, patch.object(
        outlines_endpoint, "DocumentsLoader", _fake_documents_loader(flags)
    ):
        response = _run(_stream_once_response(presentation_id, session))
        events = _run(_drain_and_collect_events(response))

    groups = next(event for event in events if event.get("type") == "quality_flags")["groups"]
    assert groups[0]["acknowledged"] is True


def test_acknowledge_quality_flag_groups_persists_group_keys():
    presentation_id = uuid.uuid4()
    presentation = _make_presentation("Some content", id=presentation_id)
    session = FakeAsyncSession(get_results={presentation_id: presentation})

    result = _run(
        outlines_endpoint.acknowledge_quality_flag_groups(
            id=presentation_id,
            payload=outlines_endpoint.AcknowledgeQualityFlagGroupsRequest(
                group_keys=["a.pdf::image_only"]
            ),
            sql_session=session,
        )
    )

    assert result["acknowledged_quality_flag_groups"] == ["a.pdf::image_only"]
    assert presentation.acknowledged_quality_flag_groups == ["a.pdf::image_only"]

    # Acknowledging a second group merges with, rather than replaces, the first.
    result2 = _run(
        outlines_endpoint.acknowledge_quality_flag_groups(
            id=presentation_id,
            payload=outlines_endpoint.AcknowledgeQualityFlagGroupsRequest(
                group_keys=["b.pptx::partial"]
            ),
            sql_session=session,
        )
    )
    assert result2["acknowledged_quality_flag_groups"] == [
        "a.pdf::image_only",
        "b.pptx::partial",
    ]


def test_each_outline_generation_gets_a_fresh_generation_id_but_manual_edits_keep_it():
    """Feedback is keyed on outline_generation_id, so it must change exactly when the
    outline is regenerated - not when the user edits the generated outline by hand."""
    presentation_id = uuid.uuid4()
    presentation = _make_presentation("Some deck content", id=presentation_id)
    session = FakeAsyncSession(get_results={presentation_id: presentation})
    calls: list = []

    p1, p2, p3 = _stream_outlines_patches(calls)
    with p1, p2, p3:
        first = _run(_stream_once(presentation_id, session))
        second = _run(_stream_once(presentation_id, session))

    assert first["outline_generation_id"] and second["outline_generation_id"]
    assert first["outline_generation_id"] != second["outline_generation_id"]
    assert str(presentation.outline_generation_id) == second["outline_generation_id"]

    from models.presentation_outline_model import PresentationOutlineModel

    edited = PresentationOutlineModel(slides=[{"content": "## Edited by hand"}])
    with patch.object(
        outlines_endpoint.MEM0_PRESENTATION_MEMORY_SERVICE,
        "store_generated_outlines",
        new=AsyncMock(),
    ):
        _run(outlines_endpoint.update_outline(id=presentation_id, outline=edited, sql_session=session))

    assert str(presentation.outline_generation_id) == second["outline_generation_id"]
