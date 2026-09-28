"""Accept a GenAI Workspace HS256 JWT and map it to a Studio ``User``.

Workspace users are keyed on ``User.external_subject`` (the JWT ``sub``, lower-cased), never on
``username``. The Workspace JWT carries ``sub``/``name``/``email``/``exp``/``iat`` and no
``iss``/``aud``, so those are validated only when present (``WORKSPACE_JWT_ISSUER`` /
``WORKSPACE_JWT_AUDIENCE``). Workspace users are never administrators.

Configuration:
- ``WORKSPACE_JWT_SECRET``: shared HS256 secret. Unset disables this whole path.
- ``STUDIO_SERVICE_API_KEY`` (see principal.py): the Workspace backend's key; with
  ``X-On-Behalf-Of`` it acts for the named Workspace user.
"""
import os
import uuid

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.sql.user import User

WORKSPACE_TOKEN_COOKIE_NAME = "studio_token"
_USERNAME_PREFIX = "ws:"
_MAX_SUBJECT_LENGTH = 200


def workspace_jwt_enabled() -> bool:
    return bool((os.getenv("WORKSPACE_JWT_SECRET") or "").strip())


def _normalize_subject(value: object) -> str | None:
    subject = str(value or "").strip().lower()
    if not subject or len(subject) > _MAX_SUBJECT_LENGTH:
        return None
    return subject


def decode_workspace_token(token: str) -> str | None:
    """Return the normalized ``sub`` of a valid Workspace token, else None."""
    secret = (os.getenv("WORKSPACE_JWT_SECRET") or "").strip()
    if not secret or not token:
        return None
    issuer = (os.getenv("WORKSPACE_JWT_ISSUER") or "").strip() or None
    audience = (os.getenv("WORKSPACE_JWT_AUDIENCE") or "").strip() or None
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": ["exp", "sub"],
                "verify_iss": issuer is not None,
                "verify_aud": audience is not None,
            },
        )
    except jwt.PyJWTError:
        return None
    return _normalize_subject(claims.get("sub"))


async def get_or_create_user_for_subject(
    session: AsyncSession, subject: str
) -> User | None:
    """Find or create the Studio account for a Workspace subject. None if deactivated."""
    normalized = _normalize_subject(subject)
    if normalized is None:
        return None

    async def _find() -> User | None:
        return (
            (await session.execute(select(User).where(User.external_subject == normalized)))
            .unique()
            .scalar_one_or_none()
        )

    user = await _find()
    if user is None:
        user = User(
            id=uuid.uuid4(),
            # Display-only. Uniqueness of the identity is external_subject; the id suffix keeps
            # `username` unique even if a local account already uses the plain form.
            username=f"{_USERNAME_PREFIX}{normalized}"[:100] + f"-{uuid.uuid4().hex[:8]}",
            external_subject=normalized,
            # Not a valid password hash format, so password login can never succeed.
            hashed_password="!external",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # Two first requests raced; the other one created the row.
            await session.rollback()
            user = await _find()
            if user is None:
                return None
        else:
            await session.refresh(user)
    return user if user.is_active else None


async def resolve_workspace_user(session: AsyncSession, token: str) -> User | None:
    subject = decode_workspace_token(token)
    if subject is None:
        return None
    return await get_or_create_user_for_subject(session, subject)
