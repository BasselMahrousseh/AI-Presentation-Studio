import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects import sqlite

from api.v1.ppt.endpoints import presentation as presentation_endpoint
from models.sql.presentation import PresentationModel, PresentationVersion


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
    session = _CapturingAsyncSession([(unfinished, None)])

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
    assert "LEFT OUTER JOIN" not in compiled
    assert "'in_progress'" not in compiled
