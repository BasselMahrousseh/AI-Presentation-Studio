import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from scripts.migrate_assets_to_s3 import migrate, AssetPlan
from models.sql.user import User
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.image_asset import ImageAsset
from services.asset_migration import assert_portable_database_references, transform_record_references
from services.asset_storage import AssetStorage, AssetStorageConfig, AssetStorageError
from tests.unit.test_asset_storage import FakeS3


@pytest.fixture
def migration_case(tmp_path):
    app = tmp_path / "old-app"
    app.mkdir()
    temp = tmp_path / "old-temp"
    temp.mkdir()
    source = temp / "brief.txt"
    source.write_bytes("Private café source".encode())
    image = app / "images" / "legacy.png"
    image.parent.mkdir()
    image.write_bytes(b"synthetic image")
    owner = uuid.uuid4()
    export = app / "exports" / "users" / str(owner) / "deck.pptx"
    export.parent.mkdir(parents=True)
    export.write_bytes(b"synthetic deck")
    database = tmp_path / "source.db"
    engine = create_engine("sqlite:///" + database.as_posix())
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(id=owner, username="workspace-user", external_subject="workspace-user", hashed_password="synthetic")
        presentation = PresentationModel(owner_id=owner, version=PresentationVersion.V2_STANDARD,
            content="Preserve source path in prose: " + str(source), n_slides=1, language="en",
            file_paths=[str(source)])
        slide = SlideModel(owner_id=owner, presentation=presentation.id, layout_group="smart", layout="slide", index=0,
            content={"title": str(image), "image": {"src": str(image)}}, properties={},
            html_content='<p>' + str(image) + '</p><img src="/app_data/images/legacy.png">')
        asset = ImageAsset(owner_id=owner, path=str(image), is_uploaded=True)
        session.add_all([user, presentation, slide, asset])
        session.commit()
        ids = (presentation.id, slide.id, asset.id)
        updated = presentation.updated_at
    client = FakeS3()
    storage = AssetStorage(AssetStorageConfig(root=str(tmp_path / "cache"), backend="s3", bucket="synthetic"), client=client)
    yield dict(app=app, temp=temp, source=source, image=image, export=export, owner=owner, database=database,
        engine=engine, storage=storage, client=client, ids=ids, updated=updated)
    engine.dispose()


def _run(case, apply=False):
    return migrate(case["database"], case["app"], case["storage"], legacy_upload_root=case["temp"], apply=apply)


def test_dry_run_never_calls_s3_or_changes_source(migration_case):
    case = migration_case
    before = case["database"].read_bytes()
    report = _run(case)
    assert report["issues"] == [] and not report["applied"]
    assert len(report["objects"]) == 3 and len(report["updates"]) == 3
    assert not case["client"].calls
    assert case["database"].read_bytes() == before
    with Session(case["engine"]) as session:
        assert session.get(ImageAsset, case["ids"][2]).path == str(case["image"])


def test_copy_verify_then_rewrite_retains_owners_prose_and_timestamps(migration_case):
    case = migration_case
    report = _run(case, apply=True)
    assert report["applied"] and report["issues"] == []
    assert len(case["client"].objects) == 3
    owner = str(case["owner"])
    with Session(case["engine"]) as session:
        presentation = session.get(PresentationModel, case["ids"][0])
        slide = session.get(SlideModel, case["ids"][1])
        asset = session.get(ImageAsset, case["ids"][2])
        assert presentation.file_paths == [f"/app_data/uploads/users/{owner}/brief.txt"]
        assert presentation.updated_at == case["updated"]
        assert str(case["source"]) in presentation.content
        assert asset.path == f"/app_data/images/users/{owner}/legacy.png"
        assert asset.owner_id == case["owner"]
        assert slide.content["title"] == str(case["image"])
        assert slide.content["image"]["src"] == asset.path
        assert f'<p>{case["image"]}</p>' in slide.html_content
        assert f'<img src="{asset.path}">' in slide.html_content
        rows = {model.__tablename__: [{column.key: getattr(record, column.key) for column in model.__table__.columns}]
            for model, record in [(PresentationModel, presentation), (SlideModel, slide), (ImageAsset, asset)]}
        assert_portable_database_references(rows)
    assert all(case[key].is_file() for key in ("source", "image", "export"))


def test_upload_failure_leaves_all_database_references_unchanged(migration_case):
    case = migration_case
    original_put = case["client"].put_object
    def fail_second(**kwargs):
        if case["client"].objects:
            raise RuntimeError("synthetic upload failure")
        return original_put(**kwargs)
    case["client"].put_object = fail_second
    with pytest.raises(AssetStorageError):
        _run(case, apply=True)
    with Session(case["engine"]) as session:
        assert session.get(ImageAsset, case["ids"][2]).path == str(case["image"])
        assert session.get(PresentationModel, case["ids"][0]).file_paths == [str(case["source"])]
    assert len(case["client"].objects) == 1  # Verified copies are harmless and reusable.
    case["client"].put_object = original_put
    assert _run(case, apply=True)["applied"]


def test_repeated_migration_with_distinct_source_and_staging_roots_is_idempotent(migration_case):
    case = migration_case
    assert _run(case, apply=True)["applied"]
    case["client"].calls.clear()
    preview = _run(case)
    assert preview["issues"] == [] and preview["updates"] == []
    assert not case["client"].calls
    assert _run(case, apply=True)["applied"]
    assert not any(call[0] == "put" for call in case["client"].calls)
    assert len(case["client"].objects) == 3


@pytest.mark.parametrize("problem", ["missing", "unmapped", "cross_owner"])
def test_preflight_blocks_missing_unowned_or_cross_owner_before_s3(migration_case, problem):
    case = migration_case
    if problem == "missing":
        case["source"].unlink()
    elif problem == "unmapped":
        with Session(case["engine"]) as session:
            session.execute(update(User).values(external_subject=None))
            session.commit()
    else:
        with Session(case["engine"]) as session:
            session.execute(update(ImageAsset).values(path=f"/app_data/images/users/{uuid.uuid4()}/private.png"))
            session.commit()
    report = _run(case, apply=True)
    assert report["issues"] and not report["applied"]
    assert not case["client"].calls


def test_one_file_with_two_owners_is_explicitly_ambiguous(migration_case):
    case = migration_case
    other = str(uuid.uuid4())
    plan = AssetPlan(case["app"], case["temp"], [str(case["owner"]), other])
    plan.transform(str(case["image"]), str(case["owner"]), "path", "images")
    with pytest.raises(ValueError, match="conflicting ownership"):
        plan.transform(str(case["image"]), other, "path", "images")


def test_absolute_studio_origins_require_explicit_mapping(migration_case):
    case = migration_case
    plan = AssetPlan(case["app"], case["temp"], [str(case["owner"])])
    value = "https://previous-studio.invalid/app_data/images/legacy.png"
    with pytest.raises(ValueError, match="legacy-origin"):
        plan.transform(value, str(case["owner"]), "src", None)
    plan.legacy_origins.add("https://previous-studio.invalid")
    assert plan.transform(value, str(case["owner"]), "src", None).startswith("/app_data/images/users/")


@pytest.mark.parametrize("reference", ["/tmp/image.png", "file:///tmp/image.png", "C:\\data\\image.png", "/app_data/images/users/other/image.png", "https://old.invalid/app_data/images/old.png", "/app_data/images/users/%2e%2e/secret", "/app_data/unknown/users/other/image.png"])
def test_portability_preflight_rejects_local_or_other_owner_references(reference):
    row = {"id": uuid.uuid4(), "owner_id": uuid.uuid4(), "path": reference}
    with pytest.raises(ValueError, match="asset references"):
        assert_portable_database_references({ImageAsset.__tablename__: [row]})


def test_media_transform_preserves_plain_user_prose_and_serialized_history():
    owner = uuid.uuid4()
    transform = lambda value, *_: value.replace("/old.png", f"/app_data/images/users/{owner}/new.png")
    row = {"owner_id": owner, "content": {"title": "/old.png", "nested": {"src": "/old.png"}, "text": '{"src":"/old.png"}'},
        "html_content": '<p>/old.png</p><img src="/old.png" style="background-image:url(/old.png)">'}
    changed = transform_record_references(SlideModel.__tablename__, row, transform)
    assert changed["content"]["title"] == "/old.png"
    assert changed["content"]["text"] == '{"src":"/old.png"}'
    assert changed["content"]["nested"]["src"].startswith("/app_data/")
    assert changed["html_content"].startswith("<p>/old.png</p>")
    assert transform_record_references("GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE", {"content": row["html_content"]}, transform) == {}


def test_font_map_is_validated_but_script_literals_and_comments_are_preserved():
    from services.asset_migration import transform_html_references
    original = '<script>const prose = \'<img src="/old.png">\';</script><!-- <img src="/old.png"> -->'
    assert transform_html_references(original, lambda _: "/new.png") == original
    row = {"id": uuid.uuid4(), "owner_id": uuid.uuid4(), "fonts": {"Company font": "C:/local/font.woff"}}
    with pytest.raises(ValueError, match="asset references"):
        assert_portable_database_references({PresentationModel.__tablename__: [row]})
    row["fonts"] = {"Company font": "/app_data/fonts/company.woff"}
    assert_portable_database_references({PresentationModel.__tablename__: [row]})
