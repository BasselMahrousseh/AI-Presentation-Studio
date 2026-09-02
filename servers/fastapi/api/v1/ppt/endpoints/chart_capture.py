import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import chart_capture_store
from services.pptx_native_chart_service import upgrade_flattened_charts_to_native
from utils.get_env import get_app_data_directory_env

LOGGER = logging.getLogger(__name__)

# Mounted alongside PRESENTATION_ROUTER (prefix "/presentation"), so the full
# path is /api/v1/ppt/presentation/export/chart-capture.
CHART_CAPTURE_ROUTER = APIRouter(prefix="/presentation/export", tags=["Presentation"])


class ChartCaptureReportRequest(BaseModel):
    token: str
    presentation_id: Optional[uuid.UUID] = None
    charts: list[dict[str, Any]] = Field(default_factory=list)


@CHART_CAPTURE_ROUTER.post("/chart-capture")
async def report_chart_capture(payload: ChartCaptureReportRequest) -> dict:
    """
    Best-effort sink for chart data captured live from the export page's
    rendered Chart.js instances. Used by pptx_native_chart_service to swap
    flattened chart images for native, editable PowerPoint charts.

    Deliberately never raises: the caller (a fire-and-forget fetch from the
    export page, racing page teardown) ignores the response either way, and
    a failure to record a chart's data simply means that chart stays a
    flattened image in the exported pptx - the safe, current behavior.
    """
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


class ChartUpgradeRequest(BaseModel):
    token: str
    presentation_id: uuid.UUID
    pptx_path: str


def _validate_pptx_export_path(pptx_path: str) -> str:
    app_data_dir = get_app_data_directory_env()
    if not app_data_dir:
        raise HTTPException(
            status_code=500, detail="APP_DATA_DIRECTORY is not configured"
        )
    exports_root = os.path.realpath(os.path.join(app_data_dir, "exports"))
    real_path = os.path.realpath(pptx_path)
    if real_path != exports_root and not real_path.startswith(
        exports_root + os.sep
    ):
        raise HTTPException(
            status_code=400,
            detail="pptx_path must be within the managed exports directory",
        )
    if not real_path.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="pptx_path must be a .pptx file")
    return real_path


@CHART_CAPTURE_ROUTER.post("/upgrade-charts")
async def upgrade_charts(payload: ChartUpgradeRequest) -> dict:
    """
    Runs the native-chart upgrade pass on an already-produced .pptx file.

    Used by the Next.js-side bundled export path
    (lib/run-bundled-presentation-export.ts), which spawns the export bundle
    directly for the interactive "Export PPTX" button and never goes through
    export_presentation()/export_utils.py - that FastAPI-side flow is a
    separate caller used for generate-and-export-in-one-request endpoints.
    Both ultimately call the same upgrade_flattened_charts_to_native(), kept
    here so python-pptx chart-building logic lives in exactly one place.

    Best-effort: any failure here leaves the pptx with its flattened chart
    images, which is the safe, already-working fallback.
    """
    real_path = _validate_pptx_export_path(payload.pptx_path)
    try:
        await upgrade_flattened_charts_to_native(
            real_path, payload.token, payload.presentation_id
        )
    except Exception:
        LOGGER.exception("chart_capture: upgrade_charts endpoint failed")
    return {"success": True}
