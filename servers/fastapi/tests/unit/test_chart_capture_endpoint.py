import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException

from api.v1.ppt.endpoints import chart_capture as endpoint


def test_report_chart_capture_stores_payload(monkeypatch):
    recorded = {}

    def _fake_write(token, presentation_id, charts):
        recorded["token"] = token
        recorded["presentation_id"] = presentation_id
        recorded["charts"] = charts

    monkeypatch.setattr(endpoint.chart_capture_store, "write_capture", _fake_write)

    presentation_id = uuid.uuid4()
    payload = endpoint.ChartCaptureReportRequest(
        token="tok-1",
        presentation_id=presentation_id,
        charts=[{"kind": "bar", "slideOrderIndex": 0}],
    )

    result = asyncio.run(endpoint.report_chart_capture(payload))

    assert result == {"success": True}
    assert recorded["token"] == "tok-1"
    assert recorded["presentation_id"] == str(presentation_id)
    assert recorded["charts"] == [{"kind": "bar", "slideOrderIndex": 0}]


def test_report_chart_capture_omitted_presentation_id_writes_empty_string(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        endpoint.chart_capture_store,
        "write_capture",
        lambda token, presentation_id, charts: recorded.update(
            presentation_id=presentation_id
        ),
    )

    payload = endpoint.ChartCaptureReportRequest(token="tok-2", charts=[])
    asyncio.run(endpoint.report_chart_capture(payload))

    assert recorded["presentation_id"] == ""


def test_report_chart_capture_never_raises_when_storage_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(endpoint.chart_capture_store, "write_capture", _boom)

    payload = endpoint.ChartCaptureReportRequest(token="tok-3", charts=[{"anything": "goes"}])

    # Must not raise despite the storage layer blowing up.
    result = asyncio.run(endpoint.report_chart_capture(payload))
    assert result == {"success": True}


# ---------------------------------------------------------------------------
# Abuse guards: this endpoint is intentionally exempt from auth (see
# api/middlewares.py), which means the caps below are what actually bounds
# what an untrusted caller can write to disk - not the pydantic model alone.
# ---------------------------------------------------------------------------


def test_charts_field_rejects_more_than_the_configured_maximum():
    with pytest.raises(Exception):
        endpoint.ChartCaptureReportRequest(
            token="tok-many",
            charts=[{"kind": "bar"}] * (endpoint._MAX_CHARTS_PER_REQUEST + 1),
        )

    # The configured maximum itself must still be accepted - this is an
    # abuse guard, not a limit on any real deck (measured: no stored slide in
    # this app's own database has more than 2 charts).
    endpoint.ChartCaptureReportRequest(
        token="tok-max",
        charts=[{"kind": "bar"}] * endpoint._MAX_CHARTS_PER_REQUEST,
    )


def test_report_chart_capture_rejects_an_oversized_payload_without_storing_it(
    monkeypatch,
):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "an oversized payload must be rejected before storage is attempted"
        )

    monkeypatch.setattr(endpoint.chart_capture_store, "write_capture", _fail_if_called)
    monkeypatch.setattr(endpoint, "_MAX_PAYLOAD_BYTES", 100)

    payload = endpoint.ChartCaptureReportRequest(
        token="tok-huge",
        charts=[{"data": "x" * 1000}],
    )

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(endpoint.report_chart_capture(payload))
    assert excinfo.value.status_code == 413


def test_report_chart_capture_accepts_a_normal_sized_payload(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        endpoint.chart_capture_store,
        "write_capture",
        lambda token, presentation_id, charts: recorded.update(charts=charts),
    )

    payload = endpoint.ChartCaptureReportRequest(
        token="tok-normal",
        charts=[{"kind": "bar", "labels": ["a", "b", "c"], "data": [1, 2, 3]}],
    )
    result = asyncio.run(endpoint.report_chart_capture(payload))

    assert result == {"success": True}
    assert recorded["charts"] == payload.charts


# ---------------------------------------------------------------------------
# /upgrade-charts - used by the Next.js-side bundled export path
# (lib/run-bundled-presentation-export.ts), which never goes through
# export_utils.py's export_presentation().
# ---------------------------------------------------------------------------


def test_validate_pptx_export_path_accepts_path_inside_exports_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    exports_dir = tmp_path / "exports" / "users" / "abc"
    exports_dir.mkdir(parents=True)
    pptx_path = exports_dir / "deck.pptx"
    pptx_path.write_bytes(b"")

    real_path = endpoint._validate_pptx_export_path(str(pptx_path))

    assert real_path == os.path.realpath(str(pptx_path))


def test_validate_pptx_export_path_rejects_path_outside_exports_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "app_data"))
    (tmp_path / "app_data").mkdir()
    outside_path = tmp_path / "elsewhere" / "deck.pptx"
    outside_path.parent.mkdir()
    outside_path.write_bytes(b"")

    with pytest.raises(HTTPException) as exc:
        endpoint._validate_pptx_export_path(str(outside_path))
    assert exc.value.status_code == 400


def test_validate_pptx_export_path_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "app_data"))
    exports_dir = tmp_path / "app_data" / "exports"
    exports_dir.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"")

    traversal_path = str(exports_dir / ".." / ".." / "secret.txt")
    with pytest.raises(HTTPException) as exc:
        endpoint._validate_pptx_export_path(traversal_path)
    assert exc.value.status_code == 400


def test_validate_pptx_export_path_rejects_non_pptx_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    not_pptx = exports_dir / "deck.pdf"
    not_pptx.write_bytes(b"")

    with pytest.raises(HTTPException) as exc:
        endpoint._validate_pptx_export_path(str(not_pptx))
    assert exc.value.status_code == 400


def test_upgrade_charts_calls_upgrade_with_validated_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    pptx_path = exports_dir / "deck.pptx"
    pptx_path.write_bytes(b"")

    recorded = {}

    async def _fake_upgrade(path, token, presentation_id):
        recorded["path"] = path
        recorded["token"] = token
        recorded["presentation_id"] = presentation_id

    monkeypatch.setattr(endpoint, "upgrade_flattened_charts_to_native", _fake_upgrade)

    presentation_id = uuid.uuid4()
    payload = endpoint.ChartUpgradeRequest(
        token="tok-x", presentation_id=presentation_id, pptx_path=str(pptx_path)
    )
    result = asyncio.run(endpoint.upgrade_charts(payload))

    assert result == {"success": True}
    assert recorded["path"] == os.path.realpath(str(pptx_path))
    assert recorded["token"] == "tok-x"
    assert recorded["presentation_id"] == presentation_id


def test_upgrade_charts_rejects_path_outside_exports_dir_before_running(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "app_data"))
    (tmp_path / "app_data").mkdir()

    called = False

    async def _fake_upgrade(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(endpoint, "upgrade_flattened_charts_to_native", _fake_upgrade)

    payload = endpoint.ChartUpgradeRequest(
        token="tok-y",
        presentation_id=uuid.uuid4(),
        pptx_path=str(tmp_path / "elsewhere.pptx"),
    )

    with pytest.raises(HTTPException):
        asyncio.run(endpoint.upgrade_charts(payload))
    assert called is False


def test_upgrade_charts_never_raises_when_upgrade_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    pptx_path = exports_dir / "deck.pptx"
    pptx_path.write_bytes(b"")

    async def _boom(*args, **kwargs):
        raise RuntimeError("corrupt pptx")

    monkeypatch.setattr(endpoint, "upgrade_flattened_charts_to_native", _boom)

    payload = endpoint.ChartUpgradeRequest(
        token="tok-z", presentation_id=uuid.uuid4(), pptx_path=str(pptx_path)
    )
    result = asyncio.run(endpoint.upgrade_charts(payload))
    assert result == {"success": True}
