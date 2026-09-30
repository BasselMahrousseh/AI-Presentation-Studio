import logging
import os
from utils.environment import load_studio_environment

load_studio_environment()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Match

from api.lifespan import app_lifespan
from api.asset_files import StoredAssetFiles
from api.middlewares import SessionAuthMiddleware
from api.v1.admin.router import API_V1_ADMIN_ROUTER
from api.v1.ppt.router import API_V1_PPT_ROUTER
from utils.get_env import (
    get_app_data_directory_env,
    get_sentry_dsn_env,
    get_sentry_send_default_pii_env,
    get_sentry_traces_sample_rate_env,
)
from utils.mime_types import init_sandbox_safe_mimetypes
from utils.path_helpers import get_resource_path


init_sandbox_safe_mimetypes()

request_logger = logging.getLogger("uvicorn.error")


def _maybe_init_sentry() -> None:
    sentry_dsn = get_sentry_dsn_env()
    if not sentry_dsn:
        return

    try:
        import sentry_sdk
    except Exception:
        # Sentry SDK is optional in some runtime targets.
        return

    traces_sample_rate = get_sentry_traces_sample_rate_env()
    send_default_pii = get_sentry_send_default_pii_env()
    try:
        parsed_sample_rate = (
            float(traces_sample_rate) if traces_sample_rate is not None else 1.0
        )
    except ValueError:
        parsed_sample_rate = 1.0

    parsed_send_default_pii = (
        send_default_pii.lower() == "true" if send_default_pii is not None else True
    )

    sentry_sdk.init(
        dsn=sentry_dsn,
        send_default_pii=parsed_send_default_pii,
        traces_sample_rate=parsed_sample_rate,
    )


_maybe_init_sentry()

app = FastAPI(lifespan=app_lifespan)

# Routers
app.include_router(API_V1_PPT_ROUTER)
app.include_router(API_V1_ADMIN_ROUTER)

# App-data bytes come from the selected durable store after ownership checks.
app_data_dir = get_app_data_directory_env()
if app_data_dir:
    os.makedirs(app_data_dir, exist_ok=True)
    app.mount("/app_data", StoredAssetFiles(directory=app_data_dir), name="app_data")

static_dir = get_resource_path("static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Electron serves Next.js and FastAPI from separate loopback ports. When its
# runtime Next.js origin is available, use that exact origin so credentialed
# requests remain standards-compliant. Docker stays same-origin behind nginx;
# the wildcard fallback preserves standalone FastAPI development behavior.
configured_origins = (
    (os.getenv("NEXT_PUBLIC_URL") or ""),
    (os.getenv("CORS_ALLOWED_ORIGINS") or ""),
)
origins = [
    origin.strip().rstrip("/")
    for value in configured_origins
    for origin in value.split(",")
    if origin.strip()
] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionAuthMiddleware)


@app.middleware("http")
async def static_icon_fallback_middleware(request: Request, call_next):
    """Serve placeholder when icon paths are missing (e.g. renamed Phosphor icons)."""
    response = await call_next(request)
    if response.status_code != 404:
        return response
    path = request.url.path
    if not path.startswith("/static/icons/"):
        return response
    placeholder = get_resource_path("static/icons/placeholder.svg")
    if not os.path.isfile(placeholder):
        return response
    return FileResponse(placeholder, media_type="image/svg+xml")


def _route_matched(request: Request) -> bool:
    for route in request.app.router.routes:
        match, _child = route.matches(request.scope)
        if match == Match.FULL:
            return True
    return False


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    """Record the method and path that actually arrived, and why a 404 happened."""
    method = request.method
    path = request.url.path
    request_logger.info("request %s %s", method, path)
    response = await call_next(request)
    if response.status_code != 404:
        request_logger.info("response %s %s %s", method, path, response.status_code)
        return response
    try:
        registered = _route_matched(request)
    except Exception:
        registered = False
    request_logger.warning(
        "404 %s %s (%s)",
        method,
        path,
        "a handler returned 404" if registered else "no route is registered for this method and path",
    )
    return response
