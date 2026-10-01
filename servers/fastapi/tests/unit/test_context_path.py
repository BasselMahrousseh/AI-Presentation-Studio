from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.context_path import ContextPathMiddleware, context_path


def test_empty_context_path_stays_at_the_root(monkeypatch):
    monkeypatch.delenv("CONTEXT_PATH", raising=False)
    assert context_path() == ""


def test_context_path_is_normalized(monkeypatch):
    monkeypatch.setenv("CONTEXT_PATH", "presentation-studio/")
    assert context_path() == "/presentation-studio"


def test_prefixed_request_reaches_the_unprefixed_route(monkeypatch):
    monkeypatch.setenv("CONTEXT_PATH", "/presentation-studio")
    inner = FastAPI()

    @inner.get("/api/v1/ppt/presentation/create")
    def create():
        return {"ok": True}

    inner.add_middleware(ContextPathMiddleware)
    client = TestClient(inner)
    prefixed = client.get("/presentation-studio/api/v1/ppt/presentation/create")
    root = client.get("/api/v1/ppt/presentation/create")
    assert prefixed.status_code == 200
    assert prefixed.json() == {"ok": True}
    assert root.status_code == 200
