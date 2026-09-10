import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException

from api.v1.ppt.endpoints import table_capture as endpoint


def test_report_table_capture_stores_payload(monkeypatch):
    recorded = {}

    def _fake_write(token, presentation_id, tables):
        recorded["token"] = token
        recorded["presentation_id"] = presentation_id
        recorded["tables"] = tables

    monkeypatch.setattr(endpoint.table_capture_store, "write_capture", _fake_write)

    presentation_id = uuid.uuid4()
    payload = endpoint.TableCaptureReportRequest(
        token="tok-1",
        presentation_id=presentation_id,
        tables=[{"rowCount": 2, "colCount": 2, "slideOrderIndex": 0}],
    )

    result = asyncio.run(endpoint.report_table_capture(payload))

    assert result == {"success": True}
    assert recorded["token"] == "tok-1"
    assert recorded["presentation_id"] == str(presentation_id)
    assert recorded["tables"] == [{"rowCount": 2, "colCount": 2, "slideOrderIndex": 0}]


def test_report_table_capture_omitted_presentation_id_writes_empty_string(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        endpoint.table_capture_store,
        "write_capture",
        lambda token, presentation_id, tables: recorded.update(
            presentation_id=presentation_id
        ),
    )

    payload = endpoint.TableCaptureReportRequest(token="tok-2", tables=[])
    asyncio.run(endpoint.report_table_capture(payload))

    assert recorded["presentation_id"] == ""


def test_report_table_capture_never_raises_when_storage_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(endpoint.table_capture_store, "write_capture", _boom)

    payload = endpoint.TableCaptureReportRequest(token="tok-3", tables=[{"anything": "goes"}])

    # Must not raise despite the storage layer blowing up.
    result = asyncio.run(endpoint.report_table_capture(payload))
    assert result == {"success": True}


# ---------------------------------------------------------------------------
# Abuse guards: this endpoint is intentionally exempt from auth (see
# api/middlewares.py), which means the caps below are what actually bounds
# what an untrusted caller can write to disk - not the pydantic model alone.
# ---------------------------------------------------------------------------


def test_tables_field_rejects_more_than_the_configured_maximum():
    with pytest.raises(Exception):
        endpoint.TableCaptureReportRequest(
            token="tok-many",
            tables=[{"rowCount": 1}] * (endpoint._MAX_TABLES_PER_REQUEST + 1),
        )

    # The configured maximum itself must still be accepted.
    endpoint.TableCaptureReportRequest(
        token="tok-max",
        tables=[{"rowCount": 1}] * endpoint._MAX_TABLES_PER_REQUEST,
    )


def test_report_table_capture_rejects_an_oversized_payload_without_storing_it(
    monkeypatch,
):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "an oversized payload must be rejected before storage is attempted"
        )

    monkeypatch.setattr(endpoint.table_capture_store, "write_capture", _fail_if_called)
    monkeypatch.setattr(endpoint, "_MAX_PAYLOAD_BYTES", 100)

    payload = endpoint.TableCaptureReportRequest(
        token="tok-huge",
        tables=[{"data": "x" * 1000}],
    )

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(endpoint.report_table_capture(payload))
    assert excinfo.value.status_code == 413


def test_report_table_capture_rejects_a_single_table_with_too_many_cells(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "a table over the per-table cell cap must be rejected before storage"
        )

    monkeypatch.setattr(endpoint.table_capture_store, "write_capture", _fail_if_called)

    oversized_table = {
        "rowCount": 1,
        "colCount": endpoint._MAX_CELLS_PER_TABLE + 1,
        "cells": [{"rowIndex": 0, "colIndex": i} for i in range(endpoint._MAX_CELLS_PER_TABLE + 1)],
    }
    payload = endpoint.TableCaptureReportRequest(token="tok-cells", tables=[oversized_table])

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(endpoint.report_table_capture(payload))
    assert excinfo.value.status_code == 413


def test_report_table_capture_accepts_a_normal_sized_payload(monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        endpoint.table_capture_store,
        "write_capture",
        lambda token, presentation_id, tables: recorded.update(tables=tables),
    )

    payload = endpoint.TableCaptureReportRequest(
        token="tok-normal",
        tables=[{"rowCount": 2, "colCount": 2, "cells": [{"rowIndex": 0, "colIndex": 0}]}],
    )
    result = asyncio.run(endpoint.report_table_capture(payload))

    assert result == {"success": True}
    assert recorded["tables"] == payload.tables


# ---------------------------------------------------------------------------
# /upgrade-tables - used by the Next.js-side bundled export path
# (lib/run-bundled-presentation-export.ts), which never goes through
# export_utils.py's export_presentation().
# ---------------------------------------------------------------------------


def test_upgrade_tables_calls_upgrade_with_validated_path(tmp_path, monkeypatch):
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

    monkeypatch.setattr(endpoint, "upgrade_flattened_tables_to_native", _fake_upgrade)

    presentation_id = uuid.uuid4()
    payload = endpoint.TableUpgradeRequest(
        token="tok-x", presentation_id=presentation_id, pptx_path=str(pptx_path)
    )
    result = asyncio.run(endpoint.upgrade_tables(payload))

    assert result == {"success": True}
    assert recorded["path"] == os.path.realpath(str(pptx_path))
    assert recorded["token"] == "tok-x"
    assert recorded["presentation_id"] == presentation_id


def test_upgrade_tables_rejects_path_outside_exports_dir_before_running(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "app_data"))
    (tmp_path / "app_data").mkdir()

    called = False

    async def _fake_upgrade(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(endpoint, "upgrade_flattened_tables_to_native", _fake_upgrade)

    payload = endpoint.TableUpgradeRequest(
        token="tok-y",
        presentation_id=uuid.uuid4(),
        pptx_path=str(tmp_path / "elsewhere.pptx"),
    )

    with pytest.raises(HTTPException):
        asyncio.run(endpoint.upgrade_tables(payload))
    assert called is False


def test_upgrade_tables_never_raises_when_upgrade_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    pptx_path = exports_dir / "deck.pptx"
    pptx_path.write_bytes(b"")

    async def _boom(*args, **kwargs):
        raise RuntimeError("corrupt pptx")

    monkeypatch.setattr(endpoint, "upgrade_flattened_tables_to_native", _boom)

    payload = endpoint.TableUpgradeRequest(
        token="tok-z", presentation_id=uuid.uuid4(), pptx_path=str(pptx_path)
    )
    result = asyncio.run(endpoint.upgrade_tables(payload))
    assert result == {"success": True}
