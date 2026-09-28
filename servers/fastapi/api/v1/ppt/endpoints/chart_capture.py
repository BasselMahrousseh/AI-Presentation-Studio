import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import chart_capture_store

LOGGER = logging.getLogger(__name__)

# Mounted alongside PRESENTATION_ROUTER (prefix "/presentation"), so the full
# path is /api/v1/ppt/presentation/export/chart-capture.
CHART_CAPTURE_ROUTER = APIRouter(prefix="/presentation/export", tags=["Presentation"])

# This endpoint is intentionally exempt from auth (see the matching entry in
# api/middlewares.py's _PUBLIC_AUTH_PATHS) so a real deck's charts are never
# silently dropped by a 401. That trade means any caller who obtains a valid
# capture token - a real risk once this is reachable without a session - can
# write arbitrarily large payloads to disk. A real deck never needs more than
# a couple of charts per slide (measured: max 2 across every stored slide in
# this app's own database), so both caps below are generous relative to real
# usage and exist only to bound abuse, not to constrain legitimate captures.
_MAX_CHARTS_PER_REQUEST = 200
_MAX_PAYLOAD_BYTES = 2_000_000


class ChartCaptureReportRequest(BaseModel):
    token: str
    presentation_id: Optional[uuid.UUID] = None
    charts: list[dict[str, Any]] = Field(
        default_factory=list, max_length=_MAX_CHARTS_PER_REQUEST
    )


@CHART_CAPTURE_ROUTER.post("/chart-capture")
async def report_chart_capture(payload: ChartCaptureReportRequest) -> dict:
    """
    Best-effort sink for chart data captured live from the export page's
    rendered Chart.js instances. Used by pptx_native_chart_service to swap
    flattened chart images for native, editable PowerPoint charts.

    Deliberately never raises for a legitimate storage failure: the caller (a
    fire-and-forget sendBeacon/fetch from the export page, racing page
    teardown) ignores the response either way, and a failure to record a
    chart's data simply means that chart stays a flattened image in the
    exported pptx - the safe, current behavior. An oversized payload is
    different - it can only come from abuse of the unauthenticated endpoint
    above, not from this app's own export page - so that case is rejected
    outright rather than silently accepted.
    """
    payload_size = len(json.dumps(payload.charts, default=str))
    if payload_size > _MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Chart capture payload too large",
        )
    try:
        chart_capture_store.write_capture(
            token=payload.token,
            presentation_id=str(payload.presentation_id) if payload.presentation_id else "",
            charts=payload.charts,
        )
        LOGGER.debug("chart_capture: full payload=%s", payload.charts)
        LOGGER.info(
            "chart_capture: stored token=%s presentation_id=%s charts=%s kinds=%s",
            payload.token,
            payload.presentation_id,
            len(payload.charts),
            [c.get("kind") for c in payload.charts],
        )
    except Exception:
        LOGGER.exception("chart_capture: failed to store reported chart capture")
    return {"success": True}
