from dataclasses import dataclass
import hmac
import re
from typing import Literal
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.sql.user import User
from api.v1.auth.workspace_jwt import (
    WORKSPACE_TOKEN_COOKIE_NAME,
    get_or_create_user_for_identity,
    workspace_identity,
    resolve_workspace_user,
)
from utils.get_env import get_studio_service_api_key_env


@dataclass(frozen=True)
class AuthPrincipal:
    """Who is calling. Studio has no accounts of its own: callers are Workspace users (their
    Workspace JWT, or the service key acting for them) or the Workspace backend itself."""

    user_id: uuid.UUID | None
    username: str
    # True only for the bare service key (no X-On-Behalf-Of): it may call /api/v1/admin/* only.
    is_admin: bool
    method: Literal["workspace", "service"]
    # The caller's Workspace JWT, handed to the export renderer, which can only send a cookie.
    workspace_token: str | None = None
    operation_id: str | None = None


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return ""


def _is_service_key(token: str) -> bool:
    service_key = (get_studio_service_api_key_env() or "").strip()
    return bool(service_key) and hmac.compare_digest(token.encode(), service_key.encode())


async def resolve_request_principal(
    request: Request, session: AsyncSession
) -> tuple[AuthPrincipal | None, User | None]:
    bearer = _bearer_token(request)

    # The Workspace backend (orchestrator): STUDIO_SERVICE_API_KEY, optionally acting for a
    # Workspace user via X-On-Behalf-Of so the deck is owned by that user.
    if bearer and _is_service_key(bearer):
        on_behalf_of = request.headers.get("X-On-Behalf-Of")
        if on_behalf_of is None:
            return AuthPrincipal(None, "service", True, "service"), None
        operation_id = request.headers.get("X-Operation-Id", "")
        action = request.headers.get("X-Workspace-Action")
        resource = request.headers.get("X-Workspace-Resource")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", operation_id):
            return None, None
        if resource != f"operation:{operation_id}":
            return None, None
        allowed = (
            (request.method == "POST" and request.url.path == "/api/v1/ppt/presentation/create" and action == "presentation.create")
            or (request.method == "GET" and request.url.path == f"/api/v1/ppt/presentation/operations/{operation_id}" and action == "presentation.reconcile")
        )
        if not allowed:
            return None, None
        identity = workspace_identity(request.headers.get("X-Workspace-Issuer"),
                                      request.headers.get("X-Workspace-Org"), on_behalf_of)
        if identity is None or request.headers.get("X-Workspace-Issuer") is None:
            return None, None
        delegate = await get_or_create_user_for_identity(session, identity)
        if delegate is None:
            return None, None
        return AuthPrincipal(delegate.id, delegate.username, False, "service", operation_id=operation_id), delegate

    # A Workspace user: `Authorization: Bearer <jwt>`, or the HttpOnly `studio_token` cookie the
    # Workspace proxy mirrors for <img>/EventSource/export rendering, which cannot set headers.
    workspace_token = bearer or request.cookies.get(WORKSPACE_TOKEN_COOKIE_NAME, "")
    if not workspace_token:
        return None, None
    user = await resolve_workspace_user(session, workspace_token)
    if user is None:
        return None, None
    return (
        AuthPrincipal(user.id, user.username, False, "workspace", workspace_token),
        user,
    )
