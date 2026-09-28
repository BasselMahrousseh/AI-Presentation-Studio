import asyncio
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
