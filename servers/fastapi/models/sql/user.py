import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy import true as sa_true, false as sa_false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlmodel import SQLModel

from utils.datetime_utils import get_current_utc_datetime
from utils.sql_types import PortableUUID, UTCDateTime


class UserBase(DeclarativeBase):
    metadata = SQLModel.metadata


class User(UserBase):
    """Username-only account model used by the FastAPI Users manager."""

    __tablename__ = "GENAI_WORKSPACE_STUDIO_USER"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID, primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    # Stable identity from the GenAI Workspace JWT `sub` claim (lower-cased). NULL for local
    # Studio accounts. Workspace users are matched on this column only, never on `username`,
    # so a Workspace user named "admin" can never resolve to the local admin account.
    external_subject: Mapped[Optional[str]] = mapped_column(
        String(256), unique=True, index=True, nullable=True
    )
    admin_slot: Mapped[Optional[str]] = mapped_column(
        String(32), unique=True, nullable=True
    )
    hashed_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_true()
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_true()
    )
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        UTCDateTime(), nullable=True, default=get_current_utc_datetime
    )
    auth_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
