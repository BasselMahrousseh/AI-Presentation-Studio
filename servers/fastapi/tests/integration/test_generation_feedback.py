"""Thumbs up/down feedback on outline and deck generations."""
import asyncio
import datetime as dt
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import api.main  # noqa: F401  (registers every table on SQLModel.metadata)
import api.middlewares as middlewares
from api.v1.admin.router import API_V1_ADMIN_ROUTER
from api.v1.ppt.endpoints.feedback import FEEDBACK_ROUTER
from api.v1.ppt.endpoints.presentation import PRESENTATION_ROUTER
from models.sql.generation_feedback import GenerationFeedback
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from services.database import get_async_session
from tests.integration.test_workspace_identity import SECRET, _bearer, _token


class FeedbackEnv:
    def __init__(self, tmp_path, monkeypatch, *, disable_auth=False):
        if disable_auth:
            monkeypatch.setenv("DISABLE_AUTH", "true")
        else:
            monkeypatch.delenv("DISABLE_AUTH", raising=False)
        monkeypatch.setenv("WORKSPACE_JWT_SECRET", SECRET)
        monkeypatch.setenv("USER_CONFIG_PATH", str(tmp_path / "userConfig.json"))
        db = tmp_path / "t.db"
        SQLModel.metadata.create_all(create_engine(f"sqlite:///{db}"))
        self.maker = async_sessionmaker(
            create_async_engine(f"sqlite+aiosqlite:///{db}"), expire_on_commit=False
        )
        monkeypatch.setattr(middlewares, "async_session_maker", self.maker)

        app = FastAPI()
        ppt = APIRouter(prefix="/api/v1/ppt")
        ppt.include_router(FEEDBACK_ROUTER)
        ppt.include_router(PRESENTATION_ROUTER)

        @ppt.get("/whoami")
        async def whoami():
            from api.v1.auth.context import get_current_owner_id

            return {"id": str(get_current_owner_id())}

        app.include_router(ppt)
        app.include_router(API_V1_ADMIN_ROUTER)

        async def override():
            async with self.maker() as s:
                yield s

        app.dependency_overrides[get_async_session] = override
        app.add_middleware(middlewares.SessionAuthMiddleware)
        self.client = TestClient(app)

    def user_id(self, sub):
        r = self.client.get("/api/v1/ppt/whoami", headers=_bearer(_token(sub)))
        return uuid.UUID(r.json()["id"])

    def make_deck(self, owner_id, *, with_outline=True, with_slides=True):
        async def go():
            async with self.maker() as s:
                p = PresentationModel(
                    id=uuid.uuid4(),
                    owner_id=owner_id,
                    version=PresentationVersion.V2_STANDARD,
                    content="c",
                    n_slides=2,
                    language="English",
                    title="t",
                    generation_mode="smart",
                    smart_template="eand",
                    outlines={"slides": [{"content": "a"}, {"content": "b"}]}
                    if with_outline
                    else None,
                    outline_generation_id=uuid.uuid4() if with_outline else None,
                    deck_generation_id=uuid.uuid4() if with_slides else None,
                    created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                    updated_at=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
                )
                s.add(p)
                if with_slides:
                    for i in range(2):
                        s.add(
                            SlideModel(
                                owner_id=owner_id, presentation=p.id, layout_group="g",
                                layout="l", index=i, content={}, properties=None,
                            )
                        )
                await s.commit()
                return p
        return asyncio.run(go())

    def presentation(self, presentation_id):
        async def go():
            async with self.maker() as s:
                return await s.get(PresentationModel, presentation_id)
        return asyncio.run(go())

    def delete_presentation(self, presentation_id):
        async def go():
            async with self.maker() as s:
                # SQLite only enforces ON DELETE SET NULL with foreign keys switched on.
                await s.execute(text("PRAGMA foreign_keys = ON"))
                await s.delete(await s.get(PresentationModel, presentation_id))
                await s.commit()
        asyncio.run(go())

    def rotate_deck_generation(self, deck_id):
        async def go():
            async with self.maker() as s:
                p = await s.get(PresentationModel, deck_id)
                p.mark_deck_generated()
                await s.commit()
                return p.deck_generation_id
        return asyncio.run(go())

    def feedback_rows(self):
        async def go():
            async with self.maker() as s:
                from sqlmodel import select

                return (await s.scalars(select(GenerationFeedback))).all()
        return asyncio.run(go())


@pytest.fixture
def env(tmp_path, monkeypatch):
    return FeedbackEnv(tmp_path, monkeypatch)


def _put(env, deck_id, stage, body, sub="alice"):
    return env.client.put(
        f"/api/v1/ppt/feedback/{deck_id}/{stage}", json=body, headers=_bearer(_token(sub))
    )


def test_second_rating_of_same_generation_updates_the_one_row(env):
    deck = env.make_deck(env.user_id("alice"))
    gen = str(deck.deck_generation_id)

    first = _put(env, deck.id, "deck", {"generation_id": gen, "rating": 1})
    assert first.status_code == 200 and first.json()["rating"] == 1

    second = _put(
        env, deck.id, "deck",
        {"generation_id": gen, "rating": -1, "reasons": ["too_much_text"], "comment": "  dense  "},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    rows = env.feedback_rows()
    assert len(rows) == 1
    row = rows[0]
    assert (row.rating, row.reasons, row.comment) == (-1, ["too_much_text"], "dense")
    # Server-side snapshot of what was rated.
    assert row.context["smart_template"] == "eand"
    assert row.context["slide_count"] == 2
    assert row.context["outline_hash"]


def test_state_endpoint_returns_current_generation_ids_and_existing_ratings(env):
    deck = env.make_deck(env.user_id("alice"))
    _put(env, deck.id, "outline", {"generation_id": str(deck.outline_generation_id), "rating": 1})

    state = env.client.get(f"/api/v1/ppt/feedback/{deck.id}", headers=_bearer(_token("alice"))).json()
    assert state["outline_generation_id"] == str(deck.outline_generation_id)
    assert state["deck_generation_id"] == str(deck.deck_generation_id)
    assert state["outline"]["rating"] == 1
    assert state["deck"] is None


def test_regenerated_deck_opens_a_fresh_rating_and_rejects_the_stale_id(env):
    deck = env.make_deck(env.user_id("alice"))
    old = str(deck.deck_generation_id)
    assert _put(env, deck.id, "deck", {"generation_id": old, "rating": -1}).status_code == 200

    new = str(env.rotate_deck_generation(deck.id))
    # A stale tab still holding the old id cannot rate the replaced generation.
    assert _put(env, deck.id, "deck", {"generation_id": old, "rating": 1}).status_code == 409

    state = env.client.get(f"/api/v1/ppt/feedback/{deck.id}", headers=_bearer(_token("alice"))).json()
    assert state["deck_generation_id"] == new and state["deck"] is None

    assert _put(env, deck.id, "deck", {"generation_id": new, "rating": 1}).status_code == 200
    assert sorted(r.rating for r in env.feedback_rows()) == [-1, 1]


def test_another_users_deck_is_a_plain_404(env):
    deck = env.make_deck(env.user_id("alice"))
    body = {"generation_id": str(deck.deck_generation_id), "rating": 1}
    assert _put(env, deck.id, "deck", body, sub="bob").status_code == 404
    assert env.client.get(
        f"/api/v1/ppt/feedback/{deck.id}", headers=_bearer(_token("bob"))
    ).status_code == 404
    assert env.feedback_rows() == []


def test_unknown_or_wrong_stage_reasons_are_rejected(env):
    deck = env.make_deck(env.user_id("alice"))
    gen = str(deck.outline_generation_id)
    # "too_much_text" is a deck reason, not an outline one.
    r = _put(env, deck.id, "outline", {"generation_id": gen, "rating": -1, "reasons": ["too_much_text"]})
    assert r.status_code == 422
    assert _put(env, deck.id, "outline", {"generation_id": gen, "rating": 0}).status_code == 422
    assert env.feedback_rows() == []


def test_thumbs_up_drops_reasons(env):
    deck = env.make_deck(env.user_id("alice"))
    r = _put(
        env, deck.id, "outline",
        {"generation_id": str(deck.outline_generation_id), "rating": 1, "reasons": ["off_topic"]},
    )
    assert r.status_code == 200 and r.json()["reasons"] == []


def test_deck_that_never_finished_generating_cannot_be_rated(env):
    deck = env.make_deck(env.user_id("alice"), with_slides=False)
    r = _put(env, deck.id, "deck", {"generation_id": str(uuid.uuid4()), "rating": 1})
    assert r.status_code == 409


def test_admin_feedback_export_spans_every_owner(tmp_path, monkeypatch):
    env = FeedbackEnv(tmp_path, monkeypatch, disable_auth=True)
    alice, bob = uuid.uuid4(), uuid.uuid4()

    async def seed():
        async with env.maker() as s:
            from models.sql.user import User

            s.add(User(id=alice, username="ws:alice", hashed_password="x", external_subject="alice"))
            s.add(User(id=bob, username="ws:bob", hashed_password="x", external_subject="bob"))
            for owner, stage, rating, reasons in (
                (alice, "deck", 1, []),
                (bob, "deck", -1, ["too_much_text", "poor_design"]),
                (bob, "outline", -1, ["off_topic"]),
            ):
                s.add(GenerationFeedback(
                    owner_id=owner, presentation_id=None, stage=stage, generation_id=uuid.uuid4(),
                    rating=rating, reasons=reasons, context={"smart_template": "eand"},
                ))
            await s.commit()

    asyncio.run(seed())

    body = env.client.get("/api/v1/admin/feedback").json()
    assert body["total"] == 3
    assert body["summary"]["deck"] == {
        "total": 2, "up": 1, "down": 1, "up_rate": 0.5,
        "top_reasons": {"too_much_text": 1, "poor_design": 1},
        "by_mode": {"eand": {"up": 1, "down": 1}},
    }
    assert {item["external_subject"] for item in body["items"]} == {"alice", "bob"}

    only_outline = env.client.get("/api/v1/admin/feedback?stage=outline").json()
    assert only_outline["total"] == 1

    csv_response = env.client.get("/api/v1/admin/feedback?format=csv")
    assert csv_response.headers["content-type"].startswith("text/csv")
    lines = csv_response.text.strip().splitlines()
    assert lines[0].startswith("created_at,updated_at,stage,rating")
    assert len(lines) == 4
    assert "too_much_text;poor_design" in csv_response.text


def _create(env, body, sub="alice"):
    return env.client.post(
        "/api/v1/ppt/presentation/create",
        json={"content": "approved outline", "generation_mode": "smart", **body},
        headers=_bearer(_token(sub)),
    )


def test_smart_deck_created_from_an_outline_links_back_to_it_in_feedback(env):
    source = env.make_deck(env.user_id("alice"), with_slides=False)
    created = _create(env, {"source_presentation_id": str(source.id)})
    assert created.status_code == 200
    assert created.json()["source_presentation_id"] == str(source.id)

    deck_id = uuid.UUID(created.json()["id"])
    assert env.presentation(deck_id).source_presentation_id == source.id
    generation_id = str(env.rotate_deck_generation(deck_id))
    assert _put(env, deck_id, "deck", {"generation_id": generation_id, "rating": -1}).status_code == 200
    assert _put(
        env, source.id, "outline",
        {"generation_id": str(source.outline_generation_id), "rating": -1},
    ).status_code == 200

    by_stage = {row.stage: row for row in env.feedback_rows()}
    assert by_stage["deck"].context["source_presentation_id"] == str(source.id)
    assert by_stage["outline"].context["source_presentation_id"] is None
    # The join an analyst needs: the deck rating's source is the outline rating's deck.
    assert by_stage["deck"].context["source_presentation_id"] == str(by_stage["outline"].presentation_id)

    # The link is a snapshot, so deleting the source nulls the column but not the feedback.
    env.delete_presentation(source.id)
    assert env.presentation(deck_id).source_presentation_id is None
    deck_row = next(row for row in env.feedback_rows() if row.stage == "deck")
    assert deck_row.context["source_presentation_id"] == str(source.id)


def test_create_without_a_source_leaves_the_link_empty(env):
    env.user_id("alice")
    created = _create(env, {})
    assert created.status_code == 200
    assert created.json()["source_presentation_id"] is None


def test_create_rejects_a_source_the_caller_does_not_own(env):
    other = env.make_deck(env.user_id("bob"))
    env.user_id("alice")
    assert _create(env, {"source_presentation_id": str(other.id)}).status_code == 404
    assert _create(env, {"source_presentation_id": str(uuid.uuid4())}).status_code == 404


def test_admin_export_includes_source_presentation_id(tmp_path, monkeypatch):
    env = FeedbackEnv(tmp_path, monkeypatch, disable_auth=True)
    source_id = str(uuid.uuid4())

    async def seed():
        async with env.maker() as s:
            s.add(GenerationFeedback(
                owner_id=None, presentation_id=None, stage="deck", generation_id=uuid.uuid4(),
                rating=-1, reasons=[], context={"source_presentation_id": source_id},
            ))
            await s.commit()

    asyncio.run(seed())

    body = env.client.get("/api/v1/admin/feedback").json()
    assert body["items"][0]["source_presentation_id"] == source_id
    csv_text = env.client.get("/api/v1/admin/feedback?format=csv").text
    header = csv_text.splitlines()[0].split(",")
    assert "source_presentation_id" in header
    assert source_id in csv_text
