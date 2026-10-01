"""A durable create outcome committed atomically with its presentation.

The presentation identifier remains as an outcome tombstone after deck deletion.
It deliberately has no deck FK; replay must never create a replacement deck.
"""
from datetime import datetime
import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlmodel import Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime
from utils.sql_types import PortableUUID, UTCDateTime


class PresentationOperation(SQLModel, table=True):
    __tablename__ = "GENAI_WORKSPACE_STUDIO_OPERATION"

    operation_key: str = Field(sa_column=Column(String(64), primary_key=True))
    operation_id: str = Field(sa_column=Column(String(128), nullable=False))
    owner_id: uuid.UUID = Field(sa_column=Column(PortableUUID, ForeignKey("GENAI_WORKSPACE_STUDIO_USER.id", ondelete="CASCADE"), nullable=False))
    request_hash: str = Field(sa_column=Column(String(64), nullable=False))
    presentation_id: uuid.UUID = Field(sa_column=Column(PortableUUID, nullable=False))
    created_at: datetime = Field(sa_column=Column(UTCDateTime(), nullable=False, default=get_current_utc_datetime))
