from datetime import datetime
from typing import List, Literal, Optional
import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlmodel import Field, SQLModel

from api.v1.auth.context import get_current_owner_id
from utils.datetime_utils import get_current_utc_datetime


FeedbackStage = Literal["outline", "deck"]


class GenerationFeedback(SQLModel, table=True):
    """One user's thumbs up/down on one outline or deck generation.

    Keyed on the generation id (PresentationModel.outline_generation_id / deck_generation_id),
    not the presentation, because regenerating overwrites a deck in place. A second rating of
    the same generation updates this row rather than adding another.
    """

    __tablename__ = "generation_feedback"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "presentation_id",
            "stage",
            "generation_id",
            name="uq_generation_feedback_owner_generation",
        ),
    )

    id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    # SET NULL, not CASCADE: feedback is product data and should outlive the deck it rated.
    presentation_id: Optional[uuid.UUID] = Field(
        sa_column=Column(
            ForeignKey("presentations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    stage: str = Field(sa_column=Column(String(16), nullable=False))
    generation_id: uuid.UUID = Field(sa_column=Column(Uuid, nullable=False))
    # +1 thumbs up, -1 thumbs down.
    rating: int = Field(sa_column=Column(SmallInteger, nullable=False))
    reasons: Optional[List[str]] = Field(sa_column=Column(JSON), default=None)
    comment: Optional[str] = Field(sa_column=Column(Text), default=None)
    # Snapshot of the deck's settings when the rating was saved (mode, slide count, template, ...).
    context: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        ),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=get_current_utc_datetime,
            onupdate=get_current_utc_datetime,
        ),
    )
