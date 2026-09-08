"""Tests for the render-slot cap on ExportTaskService (see CLAUDE.md's
"No concurrency cap on Chromium spawns" backlog item).

These stub out `_run_task_locked` (the actual node/Chromium spawn) so no real
subprocess runs - the point here is the gating logic in `_run_task`/
`_acquire_render_slot`, which is already exercised end-to-end against a real
child process in `test_runtime_limits.py`.
"""

import asyncio
import threading

import pytest
from fastapi import HTTPException

from services.export_task_service import (
    ExportTaskSaturatedError,
    ExportTaskService,
    _export_task_max_concurrency,
)


class _PeakTracker:
    """Thread-safe "how many were running at once" counter."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def exit(self):
        with self.lock:
            self.current -= 1


def _stub_run_task_locked(service: ExportTaskService, tracker: _PeakTracker, *, hold_seconds: float, fail: bool = False):
    async def _fake(task_payload, response_error_detail, **kwargs):
        tracker.enter()
        try:
            await asyncio.sleep(hold_seconds)
            if fail:
                raise HTTPException(status_code=500, detail="simulated render failure")
            return {"path": "/tmp/fake-export-output"}
        finally:
            tracker.exit()

    service._run_task_locked = _fake


def test_run_task_never_exceeds_max_concurrency_within_one_event_loop():
    service = ExportTaskService(timeout_seconds=10, max_concurrency=2)
    tracker = _PeakTracker()
    _stub_run_task_locked(service, tracker, hold_seconds=0.15)

    async def scenario():
        await asyncio.gather(
            *[service._run_task({"type": "html-to-image"}, "err") for _ in range(6)]
        )

    asyncio.run(scenario())

    assert tracker.peak <= 2
    assert service._in_flight == 0


def test_run_task_releases_slot_on_failure_so_nothing_leaks():
    service = ExportTaskService(timeout_seconds=10, max_concurrency=1)
    tracker = _PeakTracker()
    _stub_run_task_locked(service, tracker, hold_seconds=0.05, fail=True)

    async def scenario():
        for _ in range(5):
            with pytest.raises(HTTPException):
                await service._run_task({"type": "html-to-image"}, "err")

    asyncio.run(scenario())

    # If a slot leaked on any of the 5 failures, later calls would have queued
    # forever - the fact this returned at all is part of the proof, plus:
    assert tracker.peak <= 1
    assert service._in_flight == 0


def test_run_task_caps_concurrency_across_threads_with_separate_event_loops():
    """Mirrors templates/v2/tools.py's `PreviewSlideTool.render`.

    That code is synchronous and calls the shared EXPORT_TASK_SERVICE via
    `asyncio.run(...)` from inside a `ThreadPoolExecutor` (up to
    `MAX_PARALLEL_SLIDE_LAYOUTS`=10 workers at once) - each worker thread gets
    its own event loop. This is the scenario a per-event-loop
    `asyncio.Semaphore` (the pattern already used elsewhere in this codebase,
    e.g. `image_generation_service.py`) would fail to cap, since each loop
    would get its own independent semaphore. `threading.BoundedSemaphore` is
    correct here because it is shared process-wide, not per-loop.
    """
    service = ExportTaskService(timeout_seconds=10, max_concurrency=3)
    tracker = _PeakTracker()
    _stub_run_task_locked(service, tracker, hold_seconds=0.2)

    def worker():
        asyncio.run(service._run_task({"type": "html-to-image"}, "err"))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert tracker.peak <= 3
    assert service._in_flight == 0


def test_queue_timeout_raises_saturated_error_instead_of_waiting_forever():
    service = ExportTaskService(timeout_seconds=10, max_concurrency=1)
    tracker = _PeakTracker()
    _stub_run_task_locked(service, tracker, hold_seconds=0.4)

    async def scenario():
        holder = asyncio.create_task(
            service._run_task({"type": "html-to-image"}, "err")
        )
        await asyncio.sleep(0.05)  # let the holder actually take the only slot

        with pytest.raises(ExportTaskSaturatedError):
            await service._run_task(
                {"type": "html-to-image"}, "err", queue_timeout=0.1
            )

        await holder  # let the holder finish so the test doesn't leave a dangling task

    asyncio.run(scenario())


def test_bounded_wait_without_saturation_still_succeeds():
    """A caller that passes queue_timeout should still succeed normally once a
    slot frees up in time - queue_timeout only matters when it's exceeded."""
    service = ExportTaskService(timeout_seconds=10, max_concurrency=1)
    tracker = _PeakTracker()
    _stub_run_task_locked(service, tracker, hold_seconds=0.1)

    async def scenario():
        holder = asyncio.create_task(
            service._run_task({"type": "html-to-image"}, "err")
        )
        await asyncio.sleep(0.02)
        # The holder frees its slot well within this 2s bound.
        result = await service._run_task(
            {"type": "html-to-image"}, "err", queue_timeout=2.0
        )
        await holder
        return result

    result = asyncio.run(scenario())
    assert result == {"path": "/tmp/fake-export-output"}


def test_bad_max_concurrency_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("EXPORT_TASK_MAX_CONCURRENCY", "not-a-number")
    assert _export_task_max_concurrency() == 3

    monkeypatch.setenv("EXPORT_TASK_MAX_CONCURRENCY", "9999")
    assert _export_task_max_concurrency() == 3  # out of the [1, 64] range

    monkeypatch.delenv("EXPORT_TASK_MAX_CONCURRENCY", raising=False)
    assert _export_task_max_concurrency() == 3


def test_valid_max_concurrency_env_is_respected(monkeypatch):
    monkeypatch.setenv("EXPORT_TASK_MAX_CONCURRENCY", "5")
    assert _export_task_max_concurrency() == 5


def test_service_without_explicit_max_concurrency_reads_env(monkeypatch):
    monkeypatch.setenv("EXPORT_TASK_MAX_CONCURRENCY", "4")
    service = ExportTaskService(timeout_seconds=10)
    assert service._max_concurrency == 4
