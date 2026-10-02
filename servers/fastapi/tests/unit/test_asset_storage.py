import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import uuid

import httpx
import pytest
from fastapi import FastAPI, UploadFile

from api.v1.auth.context import set_current_owner_id, reset_current_owner_id
from services.asset_storage import (
    AssetStorage, AssetStorageConfig, AssetStorageError, AssetNotFound, AssetAccessDenied,
)


class ObjectError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail = False

    def head_object(self, *, Bucket, Key):
        self.calls.append(("head", Key))
        if self.fail:
            raise ObjectError("ServiceUnavailable")
        if Key not in self.objects:
            raise ObjectError("NoSuchKey")
        obj = self.objects[Key]
        return {"ContentLength": len(obj["data"]), "Metadata": obj["Metadata"]}

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs["Key"]))
        if self.fail:
            raise ObjectError("ServiceUnavailable")
        assert kwargs["IfNoneMatch"] == "*"
        if kwargs["Key"] in self.objects:
            raise ObjectError("PreconditionFailed")
        self.objects[kwargs["Key"]] = {**kwargs, "data": kwargs["Body"].read()}

    def get_object(self, *, Bucket, Key):
        self.calls.append(("get", Key))
        if self.fail:
            raise ObjectError("ServiceUnavailable")
        if Key not in self.objects:
            raise ObjectError("NoSuchKey")
        return {"Body": BytesIO(self.objects[Key]["data"])}

    def delete_object(self, *, Bucket, Key):
        self.calls.append(("delete", Key))
        if self.fail:
            raise ObjectError("ServiceUnavailable")
        self.objects.pop(Key, None)


@pytest.fixture
def stored(tmp_path, monkeypatch):
    root = tmp_path / "app_data"
    root.mkdir()
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(root))
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path / "temp"))
    monkeypatch.setenv("DISABLE_AUTH", "false")
    from api.v1.ppt.endpoints import files
    from services.temp_file_service import TempFileService
    monkeypatch.setattr(files, "TEMP_FILE_SERVICE", TempFileService())
    client = FakeS3()
    store = AssetStorage(AssetStorageConfig(root=str(root), backend="s3", bucket="test", prefix="workspace"), client=client)
    owner = uuid.uuid4()
    token = set_current_owner_id(owner)
    import services.asset_storage as module
    monkeypatch.setattr(module, "get_asset_storage", lambda: store)
    yield store, client, owner
    reset_current_owner_id(token)


def test_published_object_survives_lost_cache_and_preserves_bytes(stored, tmp_path):
    store, client, owner = stored
    source = tmp_path / "source.txt"
    source.write_bytes("Unicode café / العربية".encode())
    reference = store.publish_new(source, "uploads")
    assert reference.startswith(f"/app_data/uploads/users/{owner}/")
    obj = client.objects[store.object_key(reference)]
    assert store.object_key(reference).startswith("workspace/studio/uploads/users/")
    assert obj["ChecksumAlgorithm"] == "SHA256"
    assert obj["ServerSideEncryption"] == "AES256"
    store.local_path(reference).unlink()
    assert Path(store.materialize(reference)).read_bytes() == source.read_bytes()


def test_cached_asset_still_checks_owner_and_remote_authority(stored, tmp_path):
    store, client, owner = stored
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    reference = store.publish_new(source, "images")
    calls = len(client.calls)
    token = set_current_owner_id(uuid.uuid4())
    try:
        with pytest.raises(AssetAccessDenied):
            store.materialize(reference)
        with pytest.raises(AssetAccessDenied):
            store.delete(reference)
        assert len(client.calls) == calls
    finally:
        reset_current_owner_id(token)
    client.fail = True
    with pytest.raises(AssetStorageError):
        store.materialize(reference)
    assert store.local_path(reference).is_file()
    client.fail = False
    client.objects.clear()
    with pytest.raises(AssetNotFound):
        store.materialize(reference)


@pytest.mark.parametrize("tail", ["../other.txt", "%2e%2e/other.txt", "%252e%252e/other.txt", "a%5cb", "a?secret=x"])
def test_traversal_rejected_before_io(stored, tail):
    store, client, owner = stored
    with pytest.raises(AssetAccessDenied):
        store.materialize(f"/app_data/uploads/users/{owner}/{tail}")
    assert not client.calls


def test_s3_never_publishes_unowned_assets(stored, tmp_path, monkeypatch):
    store, client, _ = stored
    monkeypatch.setenv("DISABLE_AUTH", "true")
    source = tmp_path / "source.txt"
    source.write_text("private")
    token = set_current_owner_id(None)
    try:
        with pytest.raises(AssetAccessDenied):
            store.publish_new(source, "uploads")
    finally:
        reset_current_owner_id(token)
    assert not client.objects


def test_s3_rejects_legacy_admin_paths_and_relative_cache_cannot_bypass_remote(stored, monkeypatch, tmp_path):
    from utils.asset_directory_utils import resolve_app_path_to_filesystem
    import services.asset_storage as storage_module
    store, client, owner = stored
    monkeypatch.setattr(storage_module, "get_current_owner_is_admin", lambda: True)
    with pytest.raises(AssetAccessDenied):
        store.materialize("/app_data/images/legacy.png")
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    reference = store.publish_new(source, "images")
    relative = store.local_path(reference).relative_to(store.root / "images" / "users" / str(owner))
    assert Path(resolve_app_path_to_filesystem(relative.as_posix())).read_bytes() == b"image"
    client.fail = True
    with pytest.raises(AssetStorageError):
        resolve_app_path_to_filesystem(relative.as_posix())


def test_existing_object_collision_is_not_overwritten(stored, tmp_path):
    store, client, _ = stored
    source = tmp_path / "one.txt"
    source.write_text("one")
    reference = store.publish_new(source, "uploads")
    source.write_text("two")
    with pytest.raises(AssetStorageError, match="different content"):
        store.publish(source, reference)
    assert client.objects[store.object_key(reference)]["data"] == b"one"


def test_delete_failure_preserves_cache(stored, tmp_path):
    store, client, _ = stored
    source = tmp_path / "one.png"
    source.write_bytes(b"one")
    reference = store.publish_new(source, "images")
    client.fail = True
    with pytest.raises(AssetStorageError):
        store.delete(reference)
    assert store.local_path(reference).is_file()


def test_upload_persists_source_after_temp_restart(stored, tmp_path, monkeypatch):
    store, client, _ = stored
    from api.v1.ppt.endpoints import files
    from services.temp_file_service import TempFileService
    startup = set_current_owner_id(None)
    try:
        temporary = TempFileService()
    finally:
        reset_current_owner_id(startup)
    monkeypatch.setattr(files, "TEMP_FILE_SERVICE", temporary)
    monkeypatch.setattr(files, "get_asset_storage", lambda: store)
    async def upload():
        return await files.upload_files([UploadFile(filename="brief.txt", file=BytesIO(b"Grounded source"), size=15)])
    references = asyncio.run(upload())
    store.local_path(references[0]).unlink()
    startup = set_current_owner_id(None)
    try:
        restarted = TempFileService()
    finally:
        reset_current_owner_id(startup)
    path = restarted.resolve_temp_path(references[0], must_exist=True)
    assert Path(path).read_bytes() == b"Grounded source"
    assert restarted.validate_file_references(references) == references
    assert client.objects


def test_upload_storage_failure_is_not_success(stored, monkeypatch):
    store, client, _ = stored
    from api.v1.ppt.endpoints import files
    monkeypatch.setattr(files, "get_asset_storage", lambda: store)
    client.fail = True
    with pytest.raises(AssetStorageError):
        asyncio.run(files.upload_files([UploadFile(filename="brief.txt", file=BytesIO(b"source"), size=6)]))


def test_export_is_published_after_both_postprocessing_passes(stored, tmp_path, monkeypatch):
    store, client, _ = stored
    from utils import export_utils
    output = tmp_path / "deck.pptx"
    output.write_bytes(b"rendered")
    async def render(**kwargs):
        return SimpleNamespace(path=str(output))
    async def charts(*args):
        output.write_bytes(b"with charts")
    async def tables(*args):
        output.write_bytes(b"final charts and tables")
    monkeypatch.setattr(export_utils.EXPORT_TASK_SERVICE, "export_from_url", render)
    monkeypatch.setattr(export_utils, "upgrade_flattened_charts_to_native", charts)
    monkeypatch.setattr(export_utils, "upgrade_flattened_tables_to_native", tables)
    monkeypatch.setattr(export_utils, "get_asset_storage", lambda: store)
    result = asyncio.run(export_utils.export_presentation(uuid.uuid4(), "deck", "pptx"))
    assert client.objects[store.object_key(result.path)]["data"] == b"final charts and tables"
    store.local_path(result.path).unlink()
    assert Path(store.materialize(result.path)).read_bytes() == b"final charts and tables"


def test_image_upload_publishes_before_database_commit_and_survives_cache_loss(stored, fake_async_session, monkeypatch):
    from api.v1.ppt.endpoints import images
    from PIL import Image
    store, client, owner = stored
    monkeypatch.setattr(images, "get_asset_storage", lambda: store)
    content = BytesIO()
    Image.new("RGB", (1, 1)).save(content, format="PNG")
    result = asyncio.run(images.upload_image(UploadFile(filename="slide.png", file=BytesIO(content.getvalue())), fake_async_session))
    assert result["path"].startswith(f"/app_data/images/users/{owner}/")
    assert fake_async_session.commit_count == 1
    store.local_path(result["path"]).unlink()
    assert Path(store.materialize(result["path"])).read_bytes() == content.getvalue()
    client.fail = True
    with pytest.raises(Exception):
        asyncio.run(images.upload_image(UploadFile(filename="slide.png", file=BytesIO(content.getvalue())), fake_async_session))
    assert fake_async_session.commit_count == 1


def test_generated_image_storage_failure_propagates(stored, monkeypatch):
    from services.image_generation_service import ImageGenerationService
    from models.image_prompt import ImagePrompt
    from utils.asset_directory_utils import get_images_directory
    store, client, owner = stored
    output = Path(get_images_directory()) / "generated.png"
    output.write_bytes(b"synthetic provider bytes")
    service = ImageGenerationService.__new__(ImageGenerationService)
    service.output_directory = str(output.parent)
    service.is_image_generation_disabled = False
    service.image_gen_func = object()
    monkeypatch.setattr(service, "is_stock_provider_selected", lambda: False)
    async def provider(prompt):
        return str(output)
    monkeypatch.setattr(service, "_call_image_provider", provider)
    asset = asyncio.run(service.generate_image(ImagePrompt(prompt="Synthetic image")))
    assert asset.path.startswith(f"/app_data/images/users/{owner}/")
    assert store.object_key(asset.path) in client.objects
    client.fail = True
    with pytest.raises(Exception):
        asyncio.run(service.generate_image(ImagePrompt(prompt="Synthetic image")))


def test_asset_route_hydrates_and_denies_other_owner(stored, tmp_path, monkeypatch):
    store, client, _ = stored
    from api import asset_files
    monkeypatch.setattr(asset_files, "get_asset_storage", lambda: store)
    source = tmp_path / "download.txt"
    source.write_bytes(b"download")
    reference = store.publish_new(source, "exports")
    store.local_path(reference).unlink()
    app = FastAPI()
    app.mount("/app_data", asset_files.StoredAssetFiles(directory=store.root))
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio") as http:
            good = await http.get(reference)
            assert good.status_code == 200 and good.content == b"download"
            assert good.headers["cache-control"] == "private, no-cache"
            token = set_current_owner_id(uuid.uuid4())
            try:
                denied = await http.get(reference)
                assert denied.status_code == 404
            finally:
                reset_current_owner_id(token)
            client.fail = True
            failed = await http.get(reference)
            assert failed.status_code == 503
    asyncio.run(request())


def test_storage_configuration_rejects_missing_bucket_and_keeps_secret_repr_private(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.delenv("ARTIFACT_S3_BUCKET", raising=False)
    monkeypatch.delenv("ARTIFACT_S3_ENABLED", raising=False)
    with pytest.raises(ValueError, match="BUCKET"):
        AssetStorageConfig.from_environment()
    config = AssetStorageConfig(root=str(tmp_path), secret_key="sensitive-marker", session_token="token-marker")
    assert "sensitive-marker" not in repr(config) and "token-marker" not in repr(config)


def test_s3_selector_cannot_silently_disable_storage(monkeypatch):
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("ARTIFACT_S3_ENABLED", "false")
    with pytest.raises(ValueError, match="conflicts"):
        AssetStorageConfig.from_environment()


def test_enterprise_ca_bundle_is_validated_and_passed_to_client(monkeypatch, tmp_path):
    import boto3
    bundle = tmp_path / "ca.pem"
    bundle.write_text("synthetic certificate")
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "cache"))
    monkeypatch.setenv("ARTIFACT_S3_CA_BUNDLE", str(bundle))
    monkeypatch.setenv("ARTIFACT_S3_VERIFY_SSL", "true")
    config = AssetStorageConfig.from_environment()
    calls = []
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: calls.append(kwargs))
    AssetStorage(config)._s3()
    assert calls[0]["verify"] == str(bundle)
    monkeypatch.setenv("ARTIFACT_S3_VERIFY_SSL", "false")
    with pytest.raises(ValueError, match="CA_BUNDLE"):
        AssetStorageConfig.from_environment()


def test_durable_local_default_is_outside_temp_and_survives_restart(monkeypatch, tmp_path):
    import utils.get_env as env
    from services.temp_file_service import TempFileService
    monkeypatch.setattr(env, "__file__", str(tmp_path / "utils" / "get_env.py"))
    monkeypatch.delenv("APP_DATA_DIRECTORY", raising=False)
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path / "temporary"))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("DISABLE_AUTH", "true")
    store = AssetStorage(AssetStorageConfig.from_environment())
    assert store.root == tmp_path / "app_data"
    temporary = TempFileService()
    source = Path(temporary.create_temp_file("source.txt", b"durable"))
    reference = store.publish_new(source, "uploads")
    TempFileService()
    assert not source.exists()
    assert Path(store.materialize(reference)).read_bytes() == b"durable"


def test_cleanup_rejects_nested_app_data_without_deleting_it(monkeypatch, tmp_path):
    from services.temp_file_service import TempFileService
    cache = tmp_path / "temp" / "app_data"
    cache.mkdir(parents=True)
    source = cache / "keep.txt"
    source.write_text("keep")
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(cache))
    monkeypatch.setenv("TEMP_DIRECTORY", str(cache.parent))
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "filesystem")
    with pytest.raises(ValueError, match="outside TEMP_DIRECTORY"):
        TempFileService()
    with pytest.raises(ValueError, match="outside TEMP_DIRECTORY"):
        AssetStorageConfig.from_environment()
    assert source.read_text() == "keep"


def test_s3_rejects_legacy_temp_references_and_never_cleans_durable_assets(stored):
    from fastapi import HTTPException
    from services.temp_file_service import TempFileService
    startup = set_current_owner_id(None)
    try:
        temporary = TempFileService()
    finally:
        reset_current_owner_id(startup)
    source = temporary.create_temp_file("legacy.txt", b"source")
    with pytest.raises(HTTPException, match="Re-upload"):
        temporary.validate_file_references([source])
    store, _, _ = stored
    reference = store.publish_new(source, "uploads")
    with pytest.raises(HTTPException):
        temporary.cleanup_temp_dir(str(store.local_path(reference).parent))
    assert Path(store.materialize(reference)).read_bytes() == b"source"
