import asyncio
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.v1.ppt.endpoints import outlines as outlines_endpoint
from constants.presentation import MAX_NUMBER_OF_SLIDES
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


async def _stream_once(presentation_id: uuid.UUID, session: FakeAsyncSession) -> dict:
    response = await outlines_endpoint.stream_outlines(
        id=presentation_id,
        request=FakeRequestWithDisconnect(),
        sql_session=session,
    )
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
