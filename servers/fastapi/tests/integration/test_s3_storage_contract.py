"""Opt-in S3-compatible server test using only synthetic objects in a unique prefix."""

import os
from pathlib import Path
import uuid

import pytest

from api.v1.auth.context import set_current_owner_id, reset_current_owner_id
from services.asset_storage import AssetStorage, AssetStorageConfig, AssetAccessDenied


@pytest.mark.skipif(os.getenv("STUDIO_TEST_S3") != "1", reason="Explicit isolated S3 test opt-in required")
def test_s3_server_round_trip_cache_loss_and_owner_isolation(tmp_path, monkeypatch):
    bucket = os.getenv("STUDIO_TEST_S3_BUCKET")
    assert bucket, "Set STUDIO_TEST_S3_BUCKET to a dedicated disposable test bucket"
    monkeypatch.setenv("ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("ARTIFACT_S3_ENABLED", "true")
    monkeypatch.setenv("ARTIFACT_S3_BUCKET", bucket)
    monkeypatch.setenv("ARTIFACT_S3_PREFIX", "studio-contract-" + uuid.uuid4().hex)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "cache"))
    store = AssetStorage(AssetStorageConfig.from_environment())
    source = tmp_path / "synthetic.txt"
    source.write_bytes(b"Synthetic Studio S3 contract fixture")
    token = set_current_owner_id(uuid.uuid4())
    reference = store.new_reference("uploads", source.name)
    try:
        store.publish(source, reference)
        store.local_path(reference).unlink()
        assert Path(store.materialize(reference)).read_bytes() == source.read_bytes()
        other = set_current_owner_id(uuid.uuid4())
        try:
            with pytest.raises(AssetAccessDenied):
                store.materialize(reference)
        finally:
            reset_current_owner_id(other)
    finally:
        if reference:
            store.delete(reference)
        reset_current_owner_id(token)
