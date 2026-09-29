from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field, SQLModel
from sqlmodel.sql.sqltypes import AutoString

from api.v1.auth.context import get_current_owner_id
from utils.datetime_utils import get_current_utc_datetime
from utils.sql_types import PortableUUID, PortableJSON, UTCDateTime, RequiredText


class ImageAsset(SQLModel, table=True):
    __tablename__ = "GENAI_WORKSPACE_IMAGE_ASSET"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(PortableUUID, primary_key=True, default=uuid.uuid4))
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        exclude=True,
        sa_column=Column(
            ForeignKey("GENAI_WORKSPACE_STUDIO_USER.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            UTCDateTime(), nullable=False, default=get_current_utc_datetime
        ),
    )
    is_uploaded: bool = Field(default=False)
    path: str = Field(sa_column=Column(RequiredText(AutoString()), nullable=False))
    extras: Optional[dict] = Field(sa_column=Column(PortableJSON), default=None)
