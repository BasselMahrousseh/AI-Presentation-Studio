from dataclasses import dataclass
from typing import Literal
import uuid

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.users import UsernameUserDatabase, UserManager, get_jwt_strategy
from models.sql.access_token import AccessToken
from models.sql.user import User
from api.v1.auth.config import SESSION_COOKIE_NAME
from api.v1.auth.workspace_jwt import (
    WORKSPACE_TOKEN_COOKIE_NAME,
    get_or_create_user_for_subject,
    resolve_workspace_user,
    trusted_service_usernames,
)


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: uuid.UUID
    username: str
    is_admin: bool
    method: Literal["jwt", "api_key"]


async def resolve_request_principal(
    request: Request, session: AsyncSession
) -> tuple[AuthPrincipal | None, User | None]:
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        user_db = UsernameUserDatabase(session)
        user = await get_jwt_strategy().read_token(cookie_token, UserManager(user_db))
        if user:
            return (
                AuthPrincipal(
                    user_id=user.id,
                    username=user.username,
                    is_admin=user.is_superuser,
                    method="jwt",
                ),
                user,
            )

    authorization = request.headers.get("Authorization", "")
    bearer = (
        authorization.split(" ", 1)[1].strip()
        if authorization.lower().startswith("bearer ")
        else ""
    )

    # GenAI Workspace session: `Authorization: Bearer <jwt>`, or the HttpOnly `studio_token`
    # cookie mirrored by the Workspace proxy for <img>/EventSource, which cannot set headers.
    if bearer:
        workspace_token = "" if bearer.startswith("sk-presenton-") else bearer
    else:
        workspace_token = request.cookies.get(WORKSPACE_TOKEN_COOKIE_NAME, "")
    if workspace_token:
        user = await resolve_workspace_user(session, workspace_token)
        if user is None:
            return None, None
        return (
            AuthPrincipal(
                user_id=user.id,
                username=user.username,
                is_admin=False,
                method="jwt",
            ),
            user,
        )

    if bearer:
        token = bearer
        if not token.startswith("sk-presenton-"):
            return None, None
        access_token = await session.get(AccessToken, token)
        if access_token is None:
            return None, None
        user = await session.get(User, access_token.user_id)
        if user is None or not user.is_active or not user.is_superuser:
            return None, None

        on_behalf_of = request.headers.get("X-On-Behalf-Of")
        if on_behalf_of is not None:
            # Only keys belonging to an explicitly trusted service account may act for a user.
            # An untrusted or malformed attempt is rejected rather than silently ignored, so a
            # deck can never end up owned by the service account by accident.
            if user.username.lower() not in trusted_service_usernames():
                return None, None
            delegate = await get_or_create_user_for_subject(session, on_behalf_of)
            if delegate is None:
                return None, None
            return (
                AuthPrincipal(
                    user_id=delegate.id,
                    username=delegate.username,
                    is_admin=False,
                    method="jwt",
                ),
                delegate,
            )

        return (
            AuthPrincipal(
                user_id=user.id,
                username=user.username,
                is_admin=True,
                method="api_key",
            ),
            user,
        )

    return None, None


def principal_from_request(request: Request) -> AuthPrincipal:
    principal = getattr(request.state, "auth_principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return principal


def require_browser_admin_principal(request: Request) -> AuthPrincipal:
    principal = principal_from_request(request)
    if principal.method != "jwt" or not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin browser session required")
    return principal
