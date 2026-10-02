import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects import sqlite

from api.v1.ppt.endpoints import presentation as presentation_endpoint
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from utils.smart_brand_templates import EAND_SMART_TEMPLATE_ID


class _RowsResult:
    def __init__(self, values=None):
        self.values = values or []

    def all(self):
        return self.values

    def scalars(self):
        return self


class _CapturingAsyncSession:
    def __init__(self, values=None):
        self.executed_statement: Any = None
        self.values = values or []

    async def execute(self, statement: Any):
        self.executed_statement = statement
        return _RowsResult(self.values)


def _compile_statement(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_get_all_presentations_lists_only_smart_decks():
    session = _CapturingAsyncSession()

    response = asyncio.run(
        presentation_endpoint.get_all_presentations(
            sql_session=session,
        )
    )

    assert response == []
    compiled = _compile_statement(session.executed_statement)
    # Outline drafts and legacy TemplateV2 decks are "standard" rows and are not listed.
    assert "\"GENAI_WORKSPACE_PRESENTATION\".generation_mode = 'smart'" in compiled
    assert "\"GENAI_WORKSPACE_PRESENTATION\".version =" not in compiled
    assert "ORDER BY \"GENAI_WORKSPACE_PRESENTATION\".created_at DESC" in compiled


def test_get_all_presentations_can_skip_slide_preview_join():
    now = datetime.now(timezone.utc)
    legacy_presentation = PresentationModel(
        version=PresentationVersion.V1_STANDARD,
        content="Legacy deck",
        n_slides=4,
        language="en",
        title="Older presentation",
        fonts={"Inter": "https://example.com/inter.css"},
        created_at=now,
        updated_at=now,
    )
    session = _CapturingAsyncSession([legacy_presentation])

    response = asyncio.run(
        presentation_endpoint.get_all_presentations(
            include_slides=False,
            sql_session=session,
        )
    )

    assert len(response) == 1
    assert response[0].id == legacy_presentation.id
    assert response[0].version == PresentationVersion.V1_STANDARD
    assert response[0].slides == []
    assert response[0].fonts == {"Inter": "https://example.com/inter.css"}
    compiled = _compile_statement(session.executed_statement)
    assert "\"GENAI_WORKSPACE_PRESENTATION\".generation_mode = 'smart'" in compiled
    assert 'JOIN "GENAI_WORKSPACE_SLIDE"' not in compiled
    assert "ORDER BY \"GENAI_WORKSPACE_PRESENTATION\".created_at DESC" in compiled


def test_get_all_presentations_lists_unfinished_decks_but_not_slide_less_drafts():
    session = _CapturingAsyncSession()

    asyncio.run(
        presentation_endpoint.get_all_presentations(include_unfinished=True, sql_session=session)
    )

    compiled = _compile_statement(session.executed_statement)
    assert 'LEFT OUTER JOIN "GENAI_WORKSPACE_SLIDE"' in compiled
    assert '"GENAI_WORKSPACE_SLIDE".id IS NOT NULL' in compiled
    assert "\"GENAI_WORKSPACE_PRESENTATION\".generation_status = 'in_progress'" in compiled


def test_get_all_presentations_returns_an_unfinished_deck_with_no_first_slide():
    now = datetime.now(timezone.utc)
    unfinished = PresentationModel(
        version=PresentationVersion.V2_STANDARD,
        content="Interrupted",
        n_slides=13,
        language="en",
        title="Interrupted deck",
        generation_status="in_progress",
        created_at=now,
        updated_at=now,
    )
    session = _CapturingAsyncSession([(unfinished, None, None)])

    response = asyncio.run(
        presentation_endpoint.get_all_presentations(include_unfinished=True, sql_session=session)
    )

    assert len(response) == 1
    assert response[0].slides == []
    assert response[0].generation_status == "in_progress"


def test_get_all_presentations_keeps_inner_join_unless_unfinished_is_requested():
    session = _CapturingAsyncSession()

    asyncio.run(presentation_endpoint.get_all_presentations(sql_session=session))

    compiled = _compile_statement(session.executed_statement)
    # The first slide is inner-joined; only the e& preview slide (an alias) is optional.
    assert 'FROM "GENAI_WORKSPACE_PRESENTATION" JOIN "GENAI_WORKSPACE_SLIDE" ON' in compiled
    assert 'LEFT OUTER JOIN "GENAI_WORKSPACE_SLIDE" ON' not in compiled
    assert "'in_progress'" not in compiled


def _smart_deck(**overrides):
    now = datetime.now(timezone.utc)
    values = dict(
        version=PresentationVersion.V2_STANDARD,
        content="Deck",
        n_slides=5,
        language="en",
        title="Deck",
        generation_mode="smart",
        created_at=now,
        updated_at=now,
    )
    values.update(overrides)
    return PresentationModel(**values)


def _slide(presentation, index):
    return SlideModel(
        presentation=presentation.id,
        index=index,
        layout_group="smart",
        layout="smart",
        content={},
        html_content=f"<p>{index}</p>",
    )


def test_get_all_presentations_previews_e_and_decks_by_their_first_content_slide():
    deck = _smart_deck(smart_template=EAND_SMART_TEMPLATE_ID)
    cover, content = _slide(deck, 0), _slide(deck, 1)
    session = _CapturingAsyncSession([(deck, cover, content)])

    response = asyncio.run(
        presentation_endpoint.get_all_presentations(include_unfinished=True, sql_session=session)
    )

    assert [slide.index for slide in response[0].slides] == [1]
    compiled = _compile_statement(session.executed_statement)
    # The preview join is restricted to e& decks; other decks keep previewing their cover.
    assert f"smart_template = '{EAND_SMART_TEMPLATE_ID}'" in compiled
    assert '"GENAI_WORKSPACE_SLIDE_1"."index" = 1' in compiled


def test_get_all_presentations_falls_back_to_the_cover_without_a_content_slide():
    deck = _smart_deck(smart_template=None)
    cover = _slide(deck, 0)
    session = _CapturingAsyncSession([(deck, cover, None)])

    response = asyncio.run(presentation_endpoint.get_all_presentations(sql_session=session))

    assert [slide.index for slide in response[0].slides] == [0]


def test_get_all_presentations_keeps_a_coverless_e_and_deck_unfinished():
    # e& generation adds the cover last: a deck with content slides but no cover is still unfinished.
    deck = _smart_deck(smart_template=EAND_SMART_TEMPLATE_ID, generation_status="in_progress")
    session = _CapturingAsyncSession([(deck, None, _slide(deck, 1))])

    response = asyncio.run(
        presentation_endpoint.get_all_presentations(include_unfinished=True, sql_session=session)
    )

    assert response[0].slides == []
