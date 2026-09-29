from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel

from api.v1.auth.context import get_current_owner_id
from utils.datetime_utils import get_current_utc_datetime
from utils.sql_types import PortableUUID, PortableJSON, UTCDateTime, RequiredText, label


class ChatHistoryMessageModel(SQLModel, table=True):
    __tablename__ = "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(PortableUUID, primary_key=True, default=uuid.uuid4))
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        exclude=True,
        sa_column=Column(
            ForeignKey("GENAI_WORKSPACE_STUDIO_USER.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    presentation_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            ForeignKey("GENAI_WORKSPACE_PRESENTATION.id", ondelete="CASCADE"),
            index=True,
            nullable=True,
        )
    )
    conversation_id: uuid.UUID = Field(sa_column=Column(PortableUUID, nullable=False, index=True))
    position: int = Field(index=True, ge=1)
    role: str = Field(sa_column=Column(label(32, auto=True), nullable=False))
    content: str = Field(sa_column=Column(RequiredText(), nullable=False))
    created_at: datetime = Field(
        sa_column=Column(
            UTCDateTime(), nullable=False, default=get_current_utc_datetime
        )
    )
    tool_calls: Optional[list[str]] = Field(sa_column=Column(PortableJSON), default=None)
