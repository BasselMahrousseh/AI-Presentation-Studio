import asyncio
import os
import sys

from services.export_task_service import ExportTaskService
from services.liteparse_service import LiteParseService
from utils.runtime_limits import BoundedTextBuffer


def test_bounded_text_buffer_keeps_only_tail():
    buffer = BoundedTextBuffer(limit=5)
    buffer.append("abcdef")
    buffer.append("gh")

    value = buffer.get()

    assert "defgh" in value
    assert "truncated 3 chars" in value


def test_liteparse_plain_bridge_keeps_stdout_and_bounds_stderr(tmp_path):
    service = LiteParseService(timeout_seconds=10)
    service._npm_project_root = str(tmp_path)

    process = service._run_plain_bridge_to_text(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 5000); sys.stderr.write('e' * 10000)",
        ]
    )

    assert process.returncode == 0
    assert len(process.stdout) == 5000
    assert "truncated" in process.stderr


def test_export_child_output_is_bounded(tmp_path):
    service = ExportTaskService(timeout_seconds=10)

    result = asyncio.run(
        service._run_bounded_child(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('o' * 10000); sys.stderr.write('e' * 10000); sys.exit(7)",
            ],
            cwd=str(tmp_path),
            env=os.environ.copy(),
            timeout=10,
        )
    )

    assert result["returncode"] == 7
    assert "truncated" in str(result["stdout"])
    assert "truncated" in str(result["stderr"])


def test_export_node_env_recreates_puppeteer_directories(monkeypatch, tmp_path):
    app_data = tmp_path / "app-data"
    temp_dir = tmp_path / "temp"
    puppeteer_temp = temp_dir / "puppeteer"
    puppeteer_cache = tmp_path / "cache" / "puppeteer"
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(app_data))
    monkeypatch.setenv("TEMP_DIRECTORY", str(temp_dir))
    monkeypatch.delenv("NEXT_PUBLIC_FAST_API", raising=False)
    monkeypatch.setenv("PUPPETEER_TMP_DIR", str(puppeteer_temp))
    monkeypatch.setenv("PUPPETEER_CACHE_DIR", str(puppeteer_cache))
    monkeypatch.delenv("PRESENTON_ELECTRON", raising=False)

    service = ExportTaskService(timeout_seconds=10)
    env = service._build_node_env()

    assert env["PUPPETEER_TMP_DIR"] == str(puppeteer_temp)
    assert env["PUPPETEER_CACHE_DIR"] == str(puppeteer_cache)
    assert env["ASSETS_BASE_URL"] == "/app_data"
    assert puppeteer_temp.is_dir()
    assert puppeteer_cache.is_dir()

    puppeteer_temp.rmdir()
    puppeteer_cache.rmdir()

    service._build_node_env()

    assert puppeteer_temp.is_dir()
    assert puppeteer_cache.is_dir()


def test_export_output_path_accepts_file_path_key(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    output_path = tmp_path / "preview.png"
    output_path.write_bytes(b"png")

    assert ExportTaskService._resolve_output_path({"file_path": str(output_path)}) == str(
        output_path
    )


def test_export_output_on_another_drive_checks_each_allowed_root(monkeypatch, tmp_path):
    app_root = tmp_path / "app-data"
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    output = temp_root / "preview.png"
    output.write_bytes(b"png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(app_root))
    monkeypatch.setenv("TEMP_DIRECTORY", str(temp_root))
    original = os.path.commonpath

    def compare(paths):
        if paths[1] == os.path.realpath(app_root):
            raise ValueError("Paths are on different drives")
        return original(paths)

    monkeypatch.setattr(os.path, "commonpath", compare)
    assert ExportTaskService._resolve_trusted_runtime_path(str(output)) == str(output)
    assert ExportTaskService._resolve_trusted_runtime_path(str(outside)) is None


def test_render_html_to_image_sends_html_task_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    output_path = tmp_path / "preview.png"
    output_path.write_bytes(b"png")
    service = ExportTaskService(timeout_seconds=10)
    captured = {}

    async def fake_run_task(task_payload, response_error_detail, **_kwargs):
        captured["task_payload"] = task_payload
        captured["response_error_detail"] = response_error_detail
        return {"file_path": str(output_path)}

    service._run_task = fake_run_task

    result = asyncio.run(service.render_html_to_image("<html></html>", 320, 180))

    assert result.path == str(output_path)
    assert captured["task_payload"] == {
        "type": "html-to-image",
        "html": "<html></html>",
        "width": 320,
        "height": 180,
    }
    assert "HTML-to-image" in captured["response_error_detail"]


def test_export_converter_resolver_accepts_linux_amd64_name(tmp_path, monkeypatch):
    monkeypatch.delenv("BUILT_PYTHON_MODULE_PATH", raising=False)
    monkeypatch.setattr("services.export_task_service.sys_platform", lambda: "linux")
    monkeypatch.setattr("services.export_task_service.sys_arch", lambda: "x64")
    converter = tmp_path / "py" / "convert-linux-amd64"
    converter.parent.mkdir()
    converter.write_text("binary")

    assert ExportTaskService._resolve_converter_path(str(tmp_path)) == str(converter)


def test_export_converter_resolver_prefers_existing_configured_path(
    tmp_path, monkeypatch
):
    configured = tmp_path / "custom-converter"
    configured.write_text("binary")
    converter = tmp_path / "py" / "convert-linux-x64"
    converter.parent.mkdir()
    converter.write_text("binary")
    monkeypatch.setenv("BUILT_PYTHON_MODULE_PATH", str(configured))

    assert ExportTaskService._resolve_converter_path(str(tmp_path)) == str(configured)
