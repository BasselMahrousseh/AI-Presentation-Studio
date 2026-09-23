"""Thumbs up/down feedback on a generated outline or deck.

A rating belongs to one generation (PresentationModel.outline_generation_id /
deck_generation_id), so regenerating a deck opens a fresh rating while a second click on the
same generation just updates the existing row.
"""

import hashlib
import json
from typing import Annotated, List, Literal, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models.sql.generation_feedback import GenerationFeedback
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from services.database import get_async_session


FEEDBACK_ROUTER = APIRouter(prefix="/feedback", tags=["Feedback"])

Stage = Literal["outline", "deck"]

# Chip keys the UI may send with a thumbs down. Anything else is rejected so the reason
# counts stay clean enough to aggregate.
ALLOWED_REASONS: dict[str, frozenset[str]] = {
    "outline": frozenset(
        {
            "off_topic",
            "missing_key_points",
            "wrong_structure",
            "too_shallow",
            "wrong_slide_count",
            "language_tone",
            "other",
        }
    ),
    "deck": frozenset(
        {
            "poor_design",
            "inaccurate_content",
            "too_much_text",
            "bad_images",
            "ignored_outline",
            "broken_formatting",
            "other",
        }
    ),
}

MAX_COMMENT_LENGTH = 1000


class FeedbackRequest(BaseModel):
    generation_id: uuid.UUID
    rating: Literal[1, -1]
    reasons: List[str] = Field(default_factory=list, max_length=10)
    comment: Optional[str] = Field(default=None, max_length=MAX_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def _blank_comment_is_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    stage: Stage
    generation_id: uuid.UUID
    rating: int
    reasons: List[str]
    comment: Optional[str]


class PresentationFeedbackState(BaseModel):
    outline_generation_id: Optional[uuid.UUID]
    deck_generation_id: Optional[uuid.UUID]
    outline: Optional[FeedbackResponse]
    deck: Optional[FeedbackResponse]


def _serialize(row: GenerationFeedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=row.id,
        stage=row.stage,
        generation_id=row.generation_id,
        rating=row.rating,
        reasons=row.reasons or [],
        comment=row.comment,
    )


def _current_generation_id(
    presentation: PresentationModel, stage: Stage
) -> Optional[uuid.UUID]:
    if stage == "outline":
        return presentation.outline_generation_id
    return presentation.deck_generation_id


def _outline_hash(outlines: Optional[dict]) -> Optional[str]:
    if not outlines:
        return None
    canonical = json.dumps(outlines, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def _context_snapshot(
    sql_session: AsyncSession, presentation: PresentationModel
) -> dict:
    outline_slides = (presentation.outlines or {}).get("slides")
    slide_count = await sql_session.scalar(
        select(func.count())
        .select_from(SlideModel)
        .where(SlideModel.presentation == presentation.id)
    )
    return {
        "generation_mode": presentation.generation_mode,
        "smart_template": presentation.smart_template,
        "n_slides": presentation.n_slides,
        "language": presentation.language,
        "tone": presentation.tone,
        "verbosity": presentation.verbosity,
        "web_search": presentation.web_search,
        "has_source_files": bool(presentation.file_paths),
        "outline_slide_count": len(outline_slides)
        if isinstance(outline_slides, list)
        else None,
        "outline_hash": _outline_hash(presentation.outlines),
        "slide_count": slide_count or 0,
        # Links a Smart-flow deck back to the presentation holding its rated outline.
        "source_presentation_id": str(presentation.source_presentation_id)
        if presentation.source_presentation_id
        else None,
    }


async def _find_existing(
    sql_session: AsyncSession,
    presentation_id: uuid.UUID,
    stage: Stage,
    generation_id: uuid.UUID,
) -> Optional[GenerationFeedback]:
    # Owner scoping on ORM selects (services/database.py) limits this to the caller's rows.
    return await sql_session.scalar(
        select(GenerationFeedback).where(
            GenerationFeedback.presentation_id == presentation_id,
            GenerationFeedback.stage == stage,
            GenerationFeedback.generation_id == generation_id,
        )
    )


@FEEDBACK_ROUTER.get("/{presentation_id}", response_model=PresentationFeedbackState)
async def get_presentation_feedback(
    presentation_id: uuid.UUID,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, presentation_id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")

    state: dict = {
        "outline_generation_id": presentation.outline_generation_id,
        "deck_generation_id": presentation.deck_generation_id,
        "outline": None,
        "deck": None,
    }
    for stage in ("outline", "deck"):
        generation_id = _current_generation_id(presentation, stage)
        if generation_id is None:
            continue
        row = await _find_existing(sql_session, presentation_id, stage, generation_id)
        if row is not None:
            state[stage] = _serialize(row)
    return PresentationFeedbackState(**state)


@FEEDBACK_ROUTER.put("/{presentation_id}/{stage}", response_model=FeedbackResponse)
async def submit_feedback(
    presentation_id: uuid.UUID,
    stage: Stage,
    body: Annotated[FeedbackRequest, Body()],
    sql_session: AsyncSession = Depends(get_async_session),
):
    # Another user's deck is a plain 404 through the owner scope.
    presentation = await sql_session.get(PresentationModel, presentation_id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")

    current = _current_generation_id(presentation, stage)
    if current is None or current != body.generation_id:
        # A stale tab rating a generation that has since been replaced (or never finished).
        raise HTTPException(409, "This generation is no longer the current one")

    reasons = list(dict.fromkeys(body.reasons))
    invalid = [reason for reason in reasons if reason not in ALLOWED_REASONS[stage]]
    if invalid:
        raise HTTPException(422, f"Unknown feedback reasons: {', '.join(invalid)}")
    if body.rating == 1:
        # Reasons are chips for "what went wrong"; they mean nothing on a thumbs up.
        reasons = []

    context = await _context_snapshot(sql_session, presentation)

    for _ in range(2):
        row = await _find_existing(sql_session, presentation_id, stage, body.generation_id)
        if row is None:
            row = GenerationFeedback(
                presentation_id=presentation_id,
                stage=stage,
                generation_id=body.generation_id,
                rating=body.rating,
                reasons=reasons,
                comment=body.comment,
                context=context,
            )
        else:
            row.rating = body.rating
            row.reasons = reasons
            row.comment = body.comment
            row.context = context
        sql_session.add(row)
        try:
            await sql_session.commit()
            return _serialize(row)
        except IntegrityError:
            # Two clicks raced to insert the same generation's first rating; the loser
            # retries once as an update of the row the winner just created.
            await sql_session.rollback()
    raise HTTPException(409, "Could not save feedback, please retry")
