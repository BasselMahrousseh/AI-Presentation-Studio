"""Verified scoped Workspace identities, with an explicit legacy LDAP binding."""
from dataclasses import dataclass
import hashlib
import json
import os
import uuid

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.sql.user import User

WORKSPACE_TOKEN_COOKIE_NAME = "studio_token"
LEGACY_LDAP_ISSUER = "urn:genai-workspace:ldap"


@dataclass(frozen=True)
class WorkspaceIdentity:
    issuer: str
    organization: str
    subject: str

    @property
    def external_key(self) -> str:
        if self.issuer == LEGACY_LDAP_ISSUER and self.organization == "default":
            # Explicit compatibility binding after JWT/service authentication only.
            # Preserve existing owner UUIDs, decks and private asset paths.
            return self.subject.strip().lower()
        value = json.dumps([self.issuer, self.organization, self.subject], ensure_ascii=False, separators=(",", ":"))
        return "ws:v1:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def workspace_identity(issuer: object, organization: object, subject: object) -> WorkspaceIdentity | None:
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 200:
        return None
    if issuer is not None and (not isinstance(issuer, str) or not issuer.strip() or len(issuer) > 512):
        return None
    if not isinstance(organization, str) or not organization.strip() or len(organization) > 200:
        return None
    values = (issuer or LEGACY_LDAP_ISSUER, organization, subject)
    if any(any(ord(c) < 32 or ord(c) == 127 for c in v) for v in values):
        return None
    if values[0] == LEGACY_LDAP_ISSUER and organization == "default" and subject.strip().lower().startswith("ws:v1:"):
        return None
    return WorkspaceIdentity(*values)


def workspace_jwt_enabled() -> bool:
    return bool((os.getenv("WORKSPACE_JWT_SECRET") or "").strip())


def decode_workspace_token(token: str) -> WorkspaceIdentity | None:
    secret = (os.getenv("WORKSPACE_JWT_SECRET") or "").strip()
    if not secret or not token:
        return None
    issuer = (os.getenv("WORKSPACE_JWT_ISSUER") or "").strip() or None
    audience = (os.getenv("WORKSPACE_JWT_AUDIENCE") or "").strip() or None
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], issuer=issuer, audience=audience,
                            options={"require": ["exp", "sub"], "verify_iss": issuer is not None,
                                     "verify_aud": audience is not None})
    except jwt.PyJWTError:
        return None
    # Reserved issuer identifies only the historical issuerless LDAP credential.
    if claims.get("iss") == LEGACY_LDAP_ISSUER:
        return None
    org = claims.get("org_id", claims.get("tenant_id", "default"))
    return workspace_identity(claims.get("iss"), org, claims.get("sub"))


async def get_or_create_user_for_identity(session: AsyncSession, identity: WorkspaceIdentity) -> User | None:
    key = identity.external_key

    async def find() -> User | None:
        return (await session.execute(select(User).where(User.external_subject == key))).unique().scalar_one_or_none()

    user = await find()
    if user is None:
        user = User(id=uuid.uuid4(), username=f"ws:{identity.subject}"[:100] + f"-{uuid.uuid4().hex[:8]}",
                    external_subject=key, hashed_password="!external", is_active=True,
                    is_superuser=False, is_verified=True)
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            user = await find()
            if user is None:
                return None
        else:
            await session.refresh(user)
    return user if user.is_active and not user.is_superuser else None


async def get_or_create_user_for_subject(session: AsyncSession, subject: str) -> User | None:
    """Compatibility entry point for verified default LDAP subjects only."""
    identity = workspace_identity(None, "default", subject)
    return await get_or_create_user_for_identity(session, identity) if identity else None


async def resolve_workspace_user(session: AsyncSession, token: str) -> User | None:
    identity = decode_workspace_token(token)
    return await get_or_create_user_for_identity(session, identity) if identity else None
