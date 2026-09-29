import pytest

from services.export_task_service import ExportTaskService


@pytest.mark.parametrize("as_uri", [False, True])
def test_export_accepts_native_paths_and_file_uris(monkeypatch, tmp_path, as_uri):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    output = tmp_path / "preview with spaces.png"
    output.write_bytes(b"png")
    value = output.as_uri() if as_uri else str(output)
    assert ExportTaskService._resolve_trusted_runtime_path(value) == str(output.resolve())


def test_export_rejects_paths_outside_allowed_roots(monkeypatch, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(root))
    monkeypatch.setenv("TEMP_DIRECTORY", str(root))
    output = tmp_path / "outside.png"
    output.write_bytes(b"png")
    for value in (str(output), output.as_uri(), str(root / ".." / output.name)):
        assert ExportTaskService._resolve_trusted_runtime_path(value) is None


def test_export_rejects_remote_urls_even_when_the_path_is_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    output = tmp_path / "preview.png"
    output.write_bytes(b"png")
    uri_path = output.as_uri().removeprefix("file://")
    for value in (f"https://example.com{uri_path}", f"file://remote{uri_path}"):
        assert ExportTaskService._resolve_trusted_runtime_path(value) is None
