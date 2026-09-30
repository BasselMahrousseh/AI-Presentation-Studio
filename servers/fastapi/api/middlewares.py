import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from api.v1.auth.assets import is_app_data_path_authorized
from api.v1.auth.context import (
    reset_current_owner_id,
    reset_current_owner_is_admin,
    set_current_owner_id,
    set_current_owner_is_admin,
)
from api.v1.auth.principal import resolve_request_principal
from api.v1.auth.workspace_jwt import WORKSPACE_TOKEN_COOKIE_NAME
from services.database import async_session_maker
from utils.get_env import is_disable_auth_enabled

logger = logging.getLogger(__name__)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    _PUBLIC_AUTH_PATHS = {
        # Best-effort sink for chart data captured from the export page. It is
        # designed to be unauthenticated - see chart_capture_store.py and
        # chart_capture.py's own docstrings - because the capture call is
        # fired via navigator.sendBeacon (required to avoid the export
        # bundle's networkidle0 hang, see CLAUDE.md), which cannot attach the
        # session cookie. Safety comes from the token itself: a server-minted
        # uuid4 (utils/export_utils.py),
        # sanitized against path traversal before touching the filesystem
        # (chart_capture_store._capture_path). Without this exemption every
        # capture 401s whenever auth is enabled, and every chart in every
        # PPTX export silently stays a flattened image with no visible error.
        "/api/v1/ppt/presentation/export/chart-capture",
        # Same rationale, same mechanism, as the chart-capture exemption just
        # above - a fully separate table-capture pipeline (see CLAUDE.md's
        # table-export backlog item and pptx_native_table_service.py) fired
        # via navigator.sendBeacon for the same networkidle0 reason, safe for
        # the same "server-minted uuid4, sanitized against path traversal"
        # reason (table_capture_store._capture_path).
        "/api/v1/ppt/presentation/export/table-capture",
    }
    _PUBLIC_AUTH_PREFIXES: tuple[str, ...] = ()
    _PUBLIC_APP_DATA_PREFIXES = (
        "/app_data/fonts/",
        "/app_data/templates/",
    )
    _PROTECTED_NON_API_PATHS = {"/docs", "/openapi.json", "/redoc"}

    def _requires_auth(self, path: str) -> bool:
        if any(path.startswith(prefix) for prefix in self._PUBLIC_AUTH_PREFIXES):
            return False
        if path.startswith("/api/"):
            return True
        if any(path.startswith(prefix) for prefix in self._PUBLIC_APP_DATA_PREFIXES):
            return False
        if path.startswith("/app_data/"):
            return True
        return path in self._PROTECTED_NON_API_PATHS

    async def dispatch(self, request: Request, call_next):
        if is_disable_auth_enabled():
            # Local development only: single user, rows keep a null owner_id.
            return await call_next(request)

        path = request.url.path
        if (
            request.method == "OPTIONS"
            or not self._requires_auth(path)
            or path in self._PUBLIC_AUTH_PATHS
        ):
            return await call_next(request)

        async with async_session_maker() as session:
            principal, user = await resolve_request_principal(request, session)
            if principal is None:
                logger.info("auth rejected %s %s: no principal", request.method, path)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized"},
                )
            # The bare service key may only read the admin surface (feedback export); everything
            # else needs a user, either a Workspace JWT or the service key with X-On-Behalf-Of.
            if path.startswith("/api/v1/admin/") != principal.is_admin:
                logger.info("auth rejected %s %s: admin surface mismatch", request.method, path)
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden"},
                )
            request.state.auth_principal = principal
            request.state.current_user = user
            request.state.auth_username = principal.username
            # The export renderer calls back into FastAPI and can only carry a cookie, so a caller
            # that authenticated with a bearer token gets its Workspace JWT passed on as one.
            if principal.workspace_token and not request.headers.get("cookie"):
                request.state.export_cookie_header = (
                    f"{WORKSPACE_TOKEN_COOKIE_NAME}={principal.workspace_token}"
                )
            context_token = set_current_owner_id(principal.user_id)
            admin_context_token = set_current_owner_is_admin(principal.is_admin)
            try:
                if path.startswith(
                    "/app_data/"
                ) and not is_app_data_path_authorized(
                    path,
                    user_id=principal.user_id,
                    is_admin=principal.is_admin,
                ):
                    logger.info("auth rejected %s %s: asset not owned", request.method, path)
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "Asset not found"},
                    )
                return await call_next(request)
            finally:
                reset_current_owner_is_admin(admin_context_token)
                reset_current_owner_id(context_token)
