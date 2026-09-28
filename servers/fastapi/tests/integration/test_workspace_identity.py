"""Workspace JWT identity, the service key and on-behalf-of, favourites and the owner backfill."""
import asyncio
import datetime as dt
import importlib.util
import json
import os
import uuid

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import api.main  # noqa: F401  (registers every table on SQLModel.metadata)
import api.middlewares as middlewares
from fastapi import APIRouter
from api.v1.ppt.endpoints.presentation import PRESENTATION_ROUTER
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from services.database import get_async_session

SECRET = "workspace-shared-secret-for-tests-0123456789"
SERVICE_KEY = "studio-service-key-for-tests"


def _token(sub="alice", secret=SECRET, hours=8):
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": sub, "name": "N", "email": "n@x", "iat": now, "exp": now + dt.timedelta(hours=hours)},
        secret,
        algorithm="HS256",
    )


def _bearer(t):
    return {"Authorization": f"Bearer {t}"}


class Env:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DISABLE_AUTH", raising=False)
        monkeypatch.setenv("WORKSPACE_JWT_SECRET", SECRET)
        monkeypatch.setenv("STUDIO_SERVICE_API_KEY", SERVICE_KEY)
        self.db = tmp_path / "t.db"
        SQLModel.metadata.create_all(create_engine(f"sqlite:///{self.db}"))
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db}")
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        monkeypatch.setattr(middlewares, "async_session_maker", self.maker)
        self.api_key = SERVICE_KEY
        app = FastAPI()

        @app.get("/api/v1/ppt/whoami")
        async def whoami(request: Request):
            p = request.state.auth_principal
            return {
                "username": p.username, "is_admin": p.is_admin, "id": str(p.user_id),
                "export_cookie": getattr(request.state, "export_cookie_header", None),
            }

        ppt = APIRouter(prefix="/api/v1/ppt")
        ppt.include_router(PRESENTATION_ROUTER)
        app.include_router(ppt)

        @app.get("/api/v1/admin/ping")
        async def admin_ping():
            return {"ok": True}

        async def override():
            async with self.maker() as s:
                yield s

        app.dependency_overrides[get_async_session] = override
        app.add_middleware(middlewares.SessionAuthMiddleware)
        self.client = TestClient(app)

    def sync(self, sql, **params):
        with create_engine(f"sqlite:///{self.db}").begin() as c:
            result = c.execute(text(sql), params)
            return result.fetchall() if result.returns_rows else []


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


# ---------- JWT identity ----------

def test_valid_token_creates_stable_non_admin_user(env):
    a = env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("alice")))
    b = env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("ALICE")))
    assert a.status_code == 200 and a.json()["is_admin"] is False
    assert a.json()["id"] == b.json()["id"]  # subject is case-normalised, one account
    assert len(env.sync("select id from user where external_subject='alice'")) == 1


def test_bad_secret_expired_and_missing_token_are_rejected(env):
    for headers in ({}, _bearer(_token(secret="wrong-secret-wrong-secret-wrong-1234")), _bearer(_token(hours=-1))):
        assert env.client.get("/api/v1/ppt/whoami", headers=headers).status_code == 401


def test_cookie_mirror_is_accepted_and_a_bearer_wins_over_a_stale_cookie(env):
    ok = env.client.get("/api/v1/ppt/whoami", cookies={"studio_token": _token("bob")})
    assert ok.status_code == 200
    bearer = env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("bob")), cookies={"studio_token": "stale"})
    assert bearer.status_code == 200 and bearer.json()["id"] == ok.json()["id"]


def test_bearer_caller_hands_its_workspace_jwt_to_the_export_renderer(env):
    token = _token()
    assert env.client.get("/api/v1/ppt/whoami", headers=_bearer(token)).json()["export_cookie"] == f"studio_token={token}"


def test_without_workspace_secret_workspace_tokens_are_rejected(env, monkeypatch):
    monkeypatch.delenv("WORKSPACE_JWT_SECRET")
    assert env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token())).status_code == 401


# ---------- service key ----------

def test_service_key_acts_for_user(env):
    r = env.client.get("/api/v1/ppt/whoami", headers={**_bearer(env.api_key), "X-On-Behalf-Of": "Carol"})
    direct = env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("carol")))
    assert r.status_code == 200 and r.json()["is_admin"] is False
    assert r.json()["id"] == direct.json()["id"]


def test_bare_service_key_is_limited_to_the_admin_surface(env):
    assert env.client.get("/api/v1/admin/ping", headers=_bearer(env.api_key)).status_code == 200
    assert env.client.get("/api/v1/ppt/whoami", headers=_bearer(env.api_key)).status_code == 403


def test_workspace_users_cannot_reach_the_admin_surface(env):
    assert env.client.get("/api/v1/admin/ping", headers=_bearer(_token("admin"))).status_code == 403


def test_wrong_or_unset_service_key_is_rejected(env, monkeypatch):
    assert env.client.get("/api/v1/admin/ping", headers=_bearer("not-the-key")).status_code == 401
    monkeypatch.delenv("STUDIO_SERVICE_API_KEY")
    assert env.client.get("/api/v1/admin/ping", headers=_bearer(env.api_key)).status_code == 401


def test_on_behalf_of_is_ignored_for_plain_user_tokens(env):
    r = env.client.get("/api/v1/ppt/whoami", headers={**_bearer(_token("dave")), "X-On-Behalf-Of": "admin"})
    assert r.json()["username"].startswith("ws:dave")


# ---------- favourites ----------

def _make_deck(env, owner_id, title="t"):
    async def go():
        async with env.maker() as s:
            p = PresentationModel(
                id=uuid.uuid4(), owner_id=owner_id, version=PresentationVersion.V2_STANDARD,
                content="c", n_slides=1, language="en", title=title, generation_mode="smart",
                created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                updated_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
            )
            s.add(p)
            s.add(SlideModel(id=uuid.uuid4(), owner_id=owner_id, presentation=p.id, layout_group="g",
                             layout="l", index=0, content={}, properties=None))
            await s.commit()
            return p.id
    return asyncio.run(go())


def test_favourite_toggle_is_owner_scoped_and_does_not_touch_updated_at(env):
    a = env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("alice"))).json()["id"]
    b = env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("bob"))).json()["id"]
    deck = _make_deck(env, uuid.UUID(a))
    before = env.sync("select updated_at from presentations where id=:i", i=deck.hex)[0][0]

    other = env.client.patch(f"/api/v1/ppt/presentation/{deck}/favorite", json={"is_favorite": True}, headers=_bearer(_token("bob")))
    assert other.status_code == 404  # another user's deck is invisible, not forbidden

    mine = env.client.patch(f"/api/v1/ppt/presentation/{deck}/favorite", json={"is_favorite": True}, headers=_bearer(_token("alice")))
    assert mine.status_code == 200
    assert env.sync("select updated_at from presentations where id=:i", i=deck.hex)[0][0] == before

    listing = env.client.get("/api/v1/ppt/presentation/all?favorites_only=true", headers=_bearer(_token("alice"))).json()
    assert [p["id"] for p in listing] == [str(deck)] and listing[0]["is_favorite"] is True
    assert env.client.get("/api/v1/ppt/presentation/all?favorites_only=true", headers=_bearer(_token("bob"))).json() == []
    env.client.patch(f"/api/v1/ppt/presentation/{deck}/favorite", json={"is_favorite": False}, headers=_bearer(_token("alice")))
    assert env.client.get("/api/v1/ppt/presentation/all?favorites_only=true", headers=_bearer(_token("alice"))).json() == []
    assert b  # bob exists


def test_all_supports_last_edited_sort(env):
    a = uuid.UUID(env.client.get("/api/v1/ppt/whoami", headers=_bearer(_token("alice"))).json()["id"])
    old, new = _make_deck(env, a, "old"), _make_deck(env, a, "new")
    env.sync("update presentations set updated_at='2026-06-01 00:00:00' where id=:i", i=old.hex)
    by_edit = env.client.get("/api/v1/ppt/presentation/all?sort_by=updated_at", headers=_bearer(_token("alice"))).json()
    assert [p["title"] for p in by_edit][0] == "old"
    assert new  # created_at ties, so ordering above can only come from updated_at


# ---------- backfill ----------

def _load_backfill():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "backfill_deck_owners.py")
    spec = importlib.util.spec_from_file_location("backfill_deck_owners", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _backfill_fixture(env, tmp_path):
    app_data = tmp_path / "app_data"
    old_owner = uuid.uuid4()
    other_owner = uuid.uuid4()
    for who in (old_owner, other_owner):
        env.sync("insert into user (id, username, hashed_password, is_active, is_superuser, is_verified, auth_version) "
                 "values (:i, :n, 'x', 1, 0, 1, 1)", i=who.hex, n=f"svc-{who.hex[:6]}")
    (app_data / "images" / "users" / str(old_owner)).mkdir(parents=True)
    (app_data / "images" / "users" / str(old_owner) / "a.png").write_bytes(b"A")
    (app_data / "images" / "legacy.png").parent.mkdir(exist_ok=True, parents=True)
    (app_data / "images" / "legacy.png").write_bytes(b"L")
    mapped = _make_deck(env, old_owner, "mapped")
    unmapped = _make_deck(env, old_owner, "unmapped")
    body = {
        "img": f"/app_data/images/users/{old_owner}/a.png",
        "legacy": "/app_data/images/legacy.png",
        "foreign": f"/app_data/images/users/{other_owner}/x.png",
        "escape": "/app_data/images/../../etc/passwd",
        "gone": f"/app_data/images/users/{old_owner}/missing.png",
    }
    env.sync("update slides set content=:c where presentation=:p", c=json.dumps(body), p=mapped.hex)
    return app_data, old_owner, mapped, unmapped, body


def test_backfill_dry_run_writes_nothing(env, tmp_path):
    app_data, old_owner, mapped, unmapped, _ = _backfill_fixture(env, tmp_path)
    mod = _load_backfill()
    rep = mod.run(f"sqlite:///{env.db}", str(app_data), {str(mapped): "Erin"}, apply=False)
    assert len(rep["reassigned"]) == 1 and rep["unattributed"] == [str(unmapped)]
    assert env.sync("select owner_id from presentations where id=:i", i=mapped.hex)[0][0] == old_owner.hex
    assert env.sync("select count(*) from user where external_subject='erin'")[0][0] == 0
    assert not (app_data / "images" / "users").joinpath("x").exists()


def test_backfill_apply_reassigns_copies_files_rewrites_urls_and_is_idempotent(env, tmp_path):
    app_data, old_owner, mapped, unmapped, body = _backfill_fixture(env, tmp_path)
    mod = _load_backfill()
    mapping = {str(mapped): "Erin"}
    rep = mod.run(f"sqlite:///{env.db}", str(app_data), mapping, apply=True)

    new_owner = env.sync("select id from user where external_subject='erin'")[0][0]
    assert env.sync("select owner_id from presentations where id=:i", i=mapped.hex)[0][0] == new_owner
    assert env.sync("select owner_id from slides where presentation=:i", i=mapped.hex)[0][0] == new_owner
    # unattributed decks are untouched
    assert env.sync("select owner_id from presentations where id=:i", i=unmapped.hex)[0][0] == old_owner.hex

    new_uuid = str(uuid.UUID(new_owner))
    content = json.loads(env.sync("select content from slides where presentation=:i", i=mapped.hex)[0][0])
    assert content["img"] == f"/app_data/images/users/{new_uuid}/a.png"
    assert content["legacy"] == f"/app_data/images/users/{new_uuid}/legacy.png"
    assert (app_data / "images" / "users" / new_uuid / "a.png").read_bytes() == b"A"
    assert (app_data / "images" / "users" / new_uuid / "legacy.png").read_bytes() == b"L"
    # originals stay as the rollback path
    assert (app_data / "images" / "users" / str(old_owner) / "a.png").exists()
    # foreign-owner, traversal and missing-file refs are left alone and reported
    assert content["foreign"] == body["foreign"] and content["escape"] == body["escape"]
    assert content["gone"] == body["gone"]
    assert rep["skipped_foreign_refs"] and rep["missing_files"]

    # the new owner can now actually be authorised for the migrated asset
    from api.v1.auth.assets import is_app_data_path_authorized
    assert is_app_data_path_authorized(content["img"], user_id=uuid.UUID(new_uuid), is_admin=False)

    again = mod.run(f"sqlite:///{env.db}", str(app_data), mapping, apply=True)
    assert env.sync("select count(*) from user where external_subject='erin'")[0][0] == 1
    assert json.loads(env.sync("select content from slides where presentation=:i", i=mapped.hex)[0][0]) == content
    assert again["reassigned"][0]["from_owner"] == str(uuid.UUID(new_owner))
