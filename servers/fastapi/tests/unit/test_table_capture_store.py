import os
import time

from services import table_capture_store as store


def test_write_then_take_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    token = "abc-123"
    store.write_capture(token, "pres-1", [{"rowCount": 2}])

    result = store.take_capture(token)
    assert result == {"presentation_id": "pres-1", "tables": [{"rowCount": 2}]}


def test_take_deletes_file_after_read(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    token = "abc-456"
    store.write_capture(token, "pres-1", [])

    assert store.take_capture(token) is not None
    assert store.take_capture(token) is None  # gone on second read


def test_take_capture_unknown_token_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    assert store.take_capture("never-written") is None


def test_take_capture_empty_token_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    assert store.take_capture("") is None


def test_write_capture_empty_token_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    store.write_capture("", "pres-1", [])  # must not raise


def test_sweep_stale_captures_removes_old_keeps_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    store.write_capture("old-token", "pres-1", [])
    store.write_capture("fresh-token", "pres-1", [])

    old_path = store._capture_path("old-token")
    old_time = time.time() - 7200  # 2 hours ago
    os.utime(old_path, (old_time, old_time))

    store.sweep_stale_captures(max_age_seconds=3600)

    assert store.take_capture("old-token") is None
    assert store.take_capture("fresh-token") is not None


def test_uses_own_subdirectory_distinct_from_chart_capture(tmp_path, monkeypatch):
    """The table pipeline is a fully separate store from the chart pipeline
    (see the table-export plan's Design Decision 2) - a token written to one
    must never be readable from the other."""
    from services import chart_capture_store

    monkeypatch.setenv("TEMP_DIRECTORY", str(tmp_path))
    store.write_capture("shared-token", "pres-1", [{"rowCount": 1}])

    assert chart_capture_store.take_capture("shared-token") is None
    assert store.take_capture("shared-token") == {
        "presentation_id": "pres-1",
        "tables": [{"rowCount": 1}],
    }
