from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey
from sqlmodel import Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime
from api.v1.auth.context import get_current_owner_id


class ImageAsset(SQLModel, table=True):
    __tablename__ = "GENAI_WORKSPACE_IMAGE_ASSET"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        exclude=True,
        sa_column=Column(
            ForeignKey("GENAI_WORKSPACE_STUDIO_USER.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        ),
    )
    is_uploaded: bool = Field(default=False)
    path: str
    extras: Optional[dict] = Field(sa_column=Column(JSON), default=None)
