import asyncio

from starlette.requests import Request
from starlette.responses import Response

from api import middlewares
from api.middlewares import SessionAuthMiddleware


def test_only_shared_app_data_asset_prefixes_do_not_require_auth():
    middleware = SessionAuthMiddleware(app=None)

    assert middleware._requires_auth("/app_data/images/photo.png") is True
    assert middleware._requires_auth("/app_data/fonts/embedded/font.ttf") is False
    assert (
        middleware._requires_auth("/app_data/pptx-to-html/session/fonts/font.ttf")
        is True
    )
    assert (
        middleware._requires_auth("/app_data/templates/default/thumbnail.png") is False
    )
    assert (
        middleware._requires_auth("/app_data/pptx-to-html/session/images/image.png")
        is True
    )


def test_other_app_data_prefixes_still_require_auth():
    middleware = SessionAuthMiddleware(app=None)

    assert middleware._requires_auth("/app_data/uploads/source.pptx") is True
    assert middleware._requires_auth("/app_data/exports/deck.pdf") is True


def test_chart_capture_path_is_registered_as_a_public_auth_path():
    """`_requires_auth` alone can't express this exemption - the chart-capture
    path starts with /api/, so _requires_auth returns True for it exactly
    like every other API route. The actual bypass happens one level up, in
    dispatch()'s `path in self._PUBLIC_AUTH_PATHS` check (see the dispatch-
    level test below), the same mechanism the five /api/v1/auth/* paths use.
    This test pins the exact string so a rename of the route doesn't silently
    drop the exemption."""
    middleware = SessionAuthMiddleware(app=None)

    assert middleware._requires_auth(
        "/api/v1/ppt/presentation/export/chart-capture"
    ) is True
    assert (
        "/api/v1/ppt/presentation/export/chart-capture"
        in middleware._PUBLIC_AUTH_PATHS
    )
    # A neighboring endpoint under the same prefix must NOT be exempt - this
    # guards against a future refactor swapping the exact-string membership
    # check for a prefix match, which would accidentally exempt a real,
    # cookie-bearing endpoint under the same /presentation/export/ tree.
    assert (
        "/api/v1/ppt/presentation/export/upgrade-charts"
        not in middleware._PUBLIC_AUTH_PATHS
    )


def test_chart_capture_dispatch_bypasses_auth_entirely(monkeypatch):
    """End-to-end proof, at the same level as
    test_auth_disabled_runtime_still_checks_presenton_cloud_proxy below: a
    request with no session must still reach the route handler for this one
    path, because navigator.sendBeacon (see CLAUDE.md's networkidle0 note)
    cannot attach the session cookie the way a real authenticated request
    would. Without this exemption every capture from a real export 401s and
    native chart export silently never fires - the exact bug this middleware
    entry fixes. DISABLE_AUTH is explicitly turned off so this genuinely
    exercises the auth-required branch rather than short-circuiting past it -
    it defaults on in this project's own .env, which is exactly how the
    original bug went unnoticed."""
    monkeypatch.delenv("DISABLE_AUTH", raising=False)

    async def next_handler(_request):
        return Response("reached-the-route")

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/ppt/presentation/export/chart-capture",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 5001),
        }
    )
    response = asyncio.run(
        SessionAuthMiddleware(app=None).dispatch(request, next_handler)
    )

    assert response.body == b"reached-the-route"


def test_presenton_provider_endpoints_require_a_local_session():
    middleware = SessionAuthMiddleware(app=None)

    assert middleware._requires_auth("/api/v1/auth/presenton/status") is True
    assert middleware._requires_auth("/api/v1/auth/presenton/device/start") is True
    assert middleware._requires_auth("/api/v1/auth/presenton/device/poll") is True


def test_auth_disabled_runtime_still_checks_presenton_cloud_proxy(monkeypatch):
    captured = {}

    class SessionContext:
        async def __aenter__(self):
            return "desktop-session"

        async def __aexit__(self, *_args):
            return None

    async def proxy(request, session, user, **kwargs):
        captured.update(request=request, session=session, user=user, kwargs=kwargs)
        return Response("cloud-response")

    async def unexpected_next(_request):
        raise AssertionError("A cloud response must bypass the local route")

    monkeypatch.setattr(middlewares, "is_disable_auth_enabled", lambda: True)
    monkeypatch.setattr(middlewares, "async_session_maker", SessionContext)
    monkeypatch.setattr(
        middlewares,
        "maybe_proxy_presenton_cloud_request",
        proxy,
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/ppt/presentation/create",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 5001),
        }
    )
    response = asyncio.run(
        SessionAuthMiddleware(app=None).dispatch(request, unexpected_next)
    )

    assert response.body == b"cloud-response"
    assert captured["session"] == "desktop-session"
    assert captured["user"] is None
    assert captured["kwargs"] == {"allow_unowned": True}
