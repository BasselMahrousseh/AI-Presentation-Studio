"""Decks and outlines stop at 15 content slides, however many the user asks for."""
import json
import uuid
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.v1.ppt.endpoints import outlines as outlines_endpoint
from constants.presentation import MAX_NUMBER_OF_SLIDES
from models.presentation_outline_model import PresentationOutlineModel
from tests.conftest import FakeAsyncSession
from tests.integration.test_generation_feedback import FeedbackEnv
from tests.integration.test_outlines_endpoint import (
    _explicit_structure_content,
    _make_presentation,
    _run,
    _stream_once,
    _stream_outlines_patches,
)
from tests.integration.test_workspace_identity import _bearer, _token
from utils.llm_calls.generate_presentation_outlines import get_messages


def test_the_limit_is_15():
    assert MAX_NUMBER_OF_SLIDES == 15


@pytest.fixture
def env(tmp_path, monkeypatch):
    return FeedbackEnv(tmp_path, monkeypatch)


def _create(env, n_slides):
    return env.client.post(
        "/api/v1/ppt/presentation/create",
        json={"content": "A deck about solar power", "generation_mode": "smart",
              "n_slides": n_slides},
        headers=_bearer(_token("alice")),
    )


# ---- create: what Workspace chat offers send ("make me a 20-slide deck") ----

@pytest.mark.parametrize("requested", [16, 17, 20, 40, 100])
def test_create_asking_for_more_than_15_is_capped_not_rejected(env, requested):
    created = _create(env, requested)

    assert created.status_code == 200, created.text
    assert env.presentation(uuid.UUID(created.json()["id"])).n_slides == 15


@pytest.mark.parametrize("requested", [1, 14, 15])
def test_create_at_or_under_15_keeps_the_requested_count(env, requested):
    created = _create(env, requested)

    assert created.status_code == 200, created.text
    assert env.presentation(uuid.UUID(created.json()["id"])).n_slides == requested


def test_update_asking_for_more_than_15_is_rejected(env):
    deck = env.make_deck(env.user_id("alice"))

    updated = env.client.patch(
        "/api/v1/ppt/presentation/update",
        json={"id": str(deck.id), "n_slides": 16},
        headers=_bearer(_token("alice")),
    )

    assert updated.status_code == 400
    assert "15" in updated.json()["detail"]


# ---- outline generation ----

def _stream(presentation, llm=None):
    session = FakeAsyncSession(get_results={presentation.id: presentation})
    calls: list = []
    p1, p2, p3 = _stream_outlines_patches(calls)
    if llm is not None:
        p3 = patch.object(outlines_endpoint, "generate_ppt_outline", side_effect=llm)
    with p1, p2, p3:
        payload = _run(_stream_once(presentation.id, session))
    return calls, payload


def test_outline_for_a_deck_stored_with_more_than_15_generates_15():
    """Decks created under the old limit of 40 keep their stored count. Asking
    the model for 30 while the parser keeps 15 used to fail the count check."""
    calls, payload = _stream(_make_presentation("Solar power", n_slides=30))

    assert calls == [15]
    assert len(payload["outlines"]["slides"]) == 15


def test_content_with_more_than_15_slide_sections_gets_15_outlines():
    calls, payload = _stream(_make_presentation(_explicit_structure_content(20)))

    assert calls == [15]
    assert payload["has_explicit_slide_structure"] is True
    assert len(payload["outlines"]["slides"]) == 15


def test_model_returning_more_than_15_outlines_is_truncated_to_15():
    """Auto count: the user wrote 'give me 25 slides' and the model obliged."""
    async def overeager_llm(*_args, **_kwargs):
        yield json.dumps({"slides": [{"content": f"## Slide {i}"} for i in range(25)]})

    _, payload = _stream(_make_presentation("Give me 25 slides on solar power"), overeager_llm)

    assert len(payload["outlines"]["slides"]) == 15


def test_outline_prompt_tells_the_model_15_when_the_user_asks_for_more():
    messages = get_messages(
        content="Make a 25-slide deck on solar power",
        n_slides=None,
        language="English",
    )
    prompt = "\n".join(str(m.content) for m in messages)

    assert "Never generate more than 15 slide outlines, even if the user asks for more" in prompt
    assert "maximum 15" in prompt


def test_saving_an_outline_with_more_than_15_slides_is_rejected():
    with pytest.raises(ValidationError):
        PresentationOutlineModel(slides=[{"content": f"Slide {i}"} for i in range(16)])

    assert len(PresentationOutlineModel(
        slides=[{"content": f"Slide {i}"} for i in range(15)]).slides) == 15
