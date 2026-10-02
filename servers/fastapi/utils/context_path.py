"""context_path.py: Gateway context path. Empty means the API stays at the site root."""

import os


def context_path() -> str:
    """Return the gateway prefix. Unset defaults to ``/presentation-studio``.

    Set ``CONTEXT_PATH`` empty to serve the API at the site root.
    """
    if "CONTEXT_PATH" not in os.environ:
        raw = "/presentation-studio"
    else:
        raw = (os.environ.get("CONTEXT_PATH") or "").strip()
    if not raw or raw == "/":
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw.rstrip("/")


class ContextPathMiddleware:
    """Serve ``{CONTEXT_PATH}/api/...`` when the gateway forwards the prefix."""

    def __init__(self, app):
        self.app = app
        self.prefix = context_path()

    async def __call__(self, scope, receive, send):
        if self.prefix and scope["type"] in {"http", "websocket"}:
            path = scope.get("path") or ""
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = dict(scope)
                remainder = path[len(self.prefix) :] or "/"
                scope["path"] = remainder
                raw = scope.get("raw_path") or b""
                raw_prefix = self.prefix.encode()
                if raw.startswith(raw_prefix):
                    scope["raw_path"] = raw[len(raw_prefix) :] or b"/"
                scope["root_path"] = (scope.get("root_path") or "").rstrip("/") + self.prefix
        await self.app(scope, receive, send)
