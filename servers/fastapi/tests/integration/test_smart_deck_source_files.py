"""A Smart deck created from an approved outline must see the outline's source documents."""
import asyncio
import json
import os
import uuid

import pytest

import api.v1.ppt.endpoints.presentation as presentation_endpoints
from services.temp_file_service import TEMP_FILE_SERVICE
from tests.integration.test_generation_feedback import FeedbackEnv
from tests.integration.test_workspace_identity import _bearer, _token


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(TEMP_FILE_SERVICE, "base_dir", str(tmp_path / "temp"))
    return FeedbackEnv(tmp_path, monkeypatch)


def _owned_file(owner_id, name):
    path = os.path.join(TEMP_FILE_SERVICE.base_dir, str(owner_id), "upload", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("source")
    return os.path.realpath(path)


def _source_with_files(env, owner_id, file_paths):
    source = env.make_deck(owner_id, with_slides=False)

    async def go():
        async with env.maker() as s:
            p = await s.get(type(source), source.id)
            p.file_paths = file_paths
            await s.commit()
    asyncio.run(go())
    return source


def _create(env, body, sub="alice"):
    return env.client.post(
        "/api/v1/ppt/presentation/create",
        json={"content": "approved outline", "generation_mode": "smart", **body},
        headers=_bearer(_token(sub)),
    )


def test_deck_inherits_the_outlines_source_files(env):
    alice = env.user_id("alice")
    files = [_owned_file(alice, "a.pptx"), _owned_file(alice, "b.pdf")]
    source = _source_with_files(env, alice, files)

    created = _create(env, {"source_presentation_id": str(source.id)})

    assert created.status_code == 200
    assert env.presentation(uuid.UUID(created.json()["id"])).file_paths == files


def test_inherited_files_that_vanished_are_skipped_not_a_404(env):
    alice = env.user_id("alice")
    kept = _owned_file(alice, "a.pptx")
    gone = _owned_file(alice, "b.pdf")
    source = _source_with_files(env, alice, [kept, gone])
    os.remove(gone)

    created = _create(env, {"source_presentation_id": str(source.id)})

    assert created.status_code == 200
    assert env.presentation(uuid.UUID(created.json()["id"])).file_paths == [kept]


def test_no_surviving_inherited_files_means_no_file_paths(env):
    alice = env.user_id("alice")
    gone = _owned_file(alice, "a.pptx")
    source = _source_with_files(env, alice, [gone])
    os.remove(gone)

    created = _create(env, {"source_presentation_id": str(source.id)})

    assert created.status_code == 200
    assert env.presentation(uuid.UUID(created.json()["id"])).file_paths is None


def test_explicit_file_paths_win_over_inherited_ones(env):
    alice = env.user_id("alice")
    source = _source_with_files(env, alice, [_owned_file(alice, "a.pptx")])
    explicit = _owned_file(alice, "other.pdf")

    created = _create(
        env, {"source_presentation_id": str(source.id), "file_paths": [explicit]}
    )

    assert created.status_code == 200
    assert env.presentation(uuid.UUID(created.json()["id"])).file_paths == [explicit]


def test_another_users_outline_is_still_a_404_and_leaks_no_files(env):
    alice = env.user_id("alice")
    source = _source_with_files(env, alice, [_owned_file(alice, "a.pptx")])

    created = _create(env, {"source_presentation_id": str(source.id)}, sub="bob")

    assert created.status_code == 404


def test_smart_stream_reads_only_surviving_files(env, tmp_path, monkeypatch):
    # No request context here, so temp paths resolve against the base dir itself.
    os.makedirs(TEMP_FILE_SERVICE.base_dir, exist_ok=True)
    kept = os.path.realpath(os.path.join(TEMP_FILE_SERVICE.base_dir, "kept.pdf"))
    with open(kept, "w") as f:
        f.write("source")
    gone = os.path.join(TEMP_FILE_SERVICE.base_dir, "gone.pdf")
    deck = env.make_deck(None, with_slides=False)
    deck.file_paths = [kept, gone]

    loaded = {}

    class FakeLoader:
        def __init__(self, file_paths, presentation_language):
            loaded["paths"] = file_paths
            self.documents, self.structured_pptx_data = ["doc"], [None]

        async def load_documents(self, _temp_dir):
            pass

    class StopAfterDocuments(Exception):
        pass

    async def fake_dedup(file_paths, *_args, **_kwargs):
        loaded["dedup_paths"] = file_paths
        raise StopAfterDocuments()

    async def no_references(_ids):
        return []

    monkeypatch.setattr(presentation_endpoints, "async_session_maker", env.maker)
    monkeypatch.setattr(presentation_endpoints, "DocumentsLoader", FakeLoader)
    monkeypatch.setattr(presentation_endpoints, "build_deduplicated_context", fake_dedup)
    monkeypatch.setattr(presentation_endpoints, "load_community_references", no_references)

    async def run():
        response = await presentation_endpoints._stream_smart_presentation(deck)
        return [chunk async for chunk in response.body_iterator]

    events = [
        json.loads(line[len("data: "):])
        for chunk in asyncio.run(run())
        for line in chunk.splitlines()
        if line.startswith("data: ")
    ]
    statuses = [e.get("status") for e in events if e["type"] == "status"]

    assert loaded == {"paths": [kept], "dedup_paths": [kept]}
    assert "Some source documents are no longer available" in statuses
    assert "Reading source documents" in statuses


def test_eand_decks_keep_the_fixed_palette_even_if_colors_are_sent(env):
    env.user_id("alice")
    created = _create(env, {"smart_template": "eand", "smart_brand_colors": ["#FF0000", "#00B050"]})

    assert created.status_code == 200
    assert env.presentation(uuid.UUID(created.json()["id"])).smart_brand_colors is None


def test_standard_smart_decks_store_the_reference_deck_palette(env):
    env.user_id("alice")
    created = _create(env, {"smart_brand_colors": ["#ff0000", "#00B050"]})

    assert created.status_code == 200
    assert env.presentation(uuid.UUID(created.json()["id"])).smart_brand_colors == ["#FF0000", "#00B050"]


def test_brand_colors_are_rejected_outside_smart_mode(env):
    env.user_id("alice")
    created = _create(env, {"generation_mode": "standard", "smart_brand_colors": ["#FF0000"]})

    assert created.status_code == 400
