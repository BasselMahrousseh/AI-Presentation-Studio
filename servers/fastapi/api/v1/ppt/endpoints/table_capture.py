import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.v1.ppt.endpoints.chart_capture import _validate_pptx_export_path
from services import table_capture_store
from services.pptx_native_table_service import upgrade_flattened_tables_to_native

LOGGER = logging.getLogger(__name__)

# Mounted alongside PRESENTATION_ROUTER (prefix "/presentation"), so the full
# path is /api/v1/ppt/presentation/export/table-capture. A fully separate
# token/store/endpoint pipeline from the chart-capture one above it - not an
# extension of its schema - so table-feature code never touches the working,
# already-verified chart-capture path (see the table-export plan's Design
# Decision 2).
TABLE_CAPTURE_ROUTER = APIRouter(prefix="/presentation/export", tags=["Presentation"])

# Same rationale as the chart endpoint's caps: this endpoint is unauthenticated
# by necessity (see the matching entry in api/middlewares.py), so these bound
# abuse rather than constrain legitimate captures. No measured basis yet for
# tables specifically - retunable placeholders, reusing the chart endpoint's
# numbers as a starting point.
_MAX_TABLES_PER_REQUEST = 200
_MAX_PAYLOAD_BYTES = 2_000_000
_MAX_CELLS_PER_TABLE = 500


class TableCaptureReportRequest(BaseModel):
    token: str
    presentation_id: Optional[uuid.UUID] = None
    tables: list[dict[str, Any]] = Field(
        default_factory=list, max_length=_MAX_TABLES_PER_REQUEST
    )


def _table_cell_count(table: dict[str, Any]) -> int:
    cells = table.get("cells")
    return len(cells) if isinstance(cells, list) else 0


@TABLE_CAPTURE_ROUTER.post("/table-capture")
async def report_table_capture(payload: TableCaptureReportRequest) -> dict:
    """
    Best-effort sink for table data captured live from the export page's
    rendered <table> elements. Used by pptx_native_table_service to swap
    flattened table images for native, editable PowerPoint tables.

    Deliberately never raises for a legitimate storage failure: the caller (a
    fire-and-forget sendBeacon/fetch from the export page, racing page
    teardown) ignores the response either way, and a failure to record a
    table's data simply means that table stays a flattened image in the
    exported pptx - the safe, current behavior. An oversized payload or an
    over-large single table is different - it can only come from abuse of the
    unauthenticated endpoint above, not from this app's own export page - so
    those cases are rejected outright rather than silently accepted.
    """
    for table in payload.tables:
        if _table_cell_count(table) > _MAX_CELLS_PER_TABLE:
            raise HTTPException(
                status_code=413,
                detail="Table capture has too many cells",
            )

    payload_size = len(json.dumps(payload.tables, default=str))
    if payload_size > _MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Table capture payload too large",
        )
    try:
        table_capture_store.write_capture(
            token=payload.token,
            presentation_id=str(payload.presentation_id) if payload.presentation_id else "",
            tables=payload.tables,
        )
        LOGGER.debug("table_capture: full payload=%s", payload.tables)
        LOGGER.info(
            "table_capture: stored token=%s presentation_id=%s tables=%s",
            payload.token,
            payload.presentation_id,
            len(payload.tables),
        )
    except Exception:
        LOGGER.exception("table_capture: failed to store reported table capture")
    return {"success": True}


class TableUpgradeRequest(BaseModel):
    token: str
    presentation_id: uuid.UUID
    pptx_path: str


@TABLE_CAPTURE_ROUTER.post("/upgrade-tables")
async def upgrade_tables(payload: TableUpgradeRequest) -> dict:
    """
    Runs the native-table upgrade pass on an already-produced .pptx file.

    Used by the Next.js-side bundled export path
    (lib/run-bundled-presentation-export.ts), which spawns the export bundle
    directly for the interactive "Export PPTX" button and never goes through
    export_presentation()/export_utils.py - that FastAPI-side flow is a
    separate caller used for generate-and-export-in-one-request endpoints.
    Both ultimately call the same upgrade_flattened_tables_to_native(), kept
    here so python-pptx table-building logic lives in exactly one place.

    Must run strictly after the equivalent chart upgrade for the same file
    has already completed and saved (see the table-export plan's Design
    Decision 3) - both callers of this endpoint enforce that ordering.

    Best-effort: any failure here leaves the pptx with its flattened table
    images, which is the safe, already-working fallback.
    """
    real_path = _validate_pptx_export_path(payload.pptx_path)
    try:
        await upgrade_flattened_tables_to_native(
            real_path, payload.token, payload.presentation_id
        )
    except Exception:
        LOGGER.exception("table_capture: upgrade_tables endpoint failed")
    return {"success": True}
