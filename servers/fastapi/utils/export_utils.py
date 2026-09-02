import os
import logging
from typing import Literal
from urllib.parse import urlencode
import uuid

from pathvalidate import sanitize_filename

from models.presentation_and_path import PresentationAndPath
from utils.filename_utils import safe_export_basename
from services.export_task_service import EXPORT_TASK_SERVICE
from services.pptx_native_chart_service import upgrade_flattened_charts_to_native
from utils.runtime_limits import log_memory


LOGGER = logging.getLogger(__name__)


def _get_next_public_url() -> str:
    return (os.getenv("NEXT_PUBLIC_URL") or "").strip() or "http://127.0.0.1"


def _get_next_public_fastapi_url() -> str | None:
    value = (os.getenv("NEXT_PUBLIC_FAST_API") or "").strip()
    return value or None


def _build_presentation_export_url(
    presentation_id: uuid.UUID,
    cookie_header: str | None = None,
    chart_capture_token: str | None = None,
) -> tuple[str, str | None]:
    params = {"id": str(presentation_id)}
    fastapi_url = _get_next_public_fastapi_url()
    if fastapi_url:
        params["fastapiUrl"] = fastapi_url
    if chart_capture_token:
        params["chartCaptureToken"] = chart_capture_token
    export_url = f"{_get_next_public_url().rstrip('/')}/pdf-maker?{urlencode(params)}"
    if cookie_header:
        export_url = f"{export_url}#{urlencode({'exportCookie': cookie_header})}"
    return (
        export_url,
        fastapi_url,
    )


async def export_presentation(
    presentation_id: uuid.UUID,
    title: str,
    export_as: Literal["pptx", "pdf"],
    cookie_header: str | None = None,
) -> PresentationAndPath:
    log_memory(
        LOGGER,
        "presentation.export.start",
        presentation_id=str(presentation_id),
        export_as=export_as,
    )
    chart_capture_token = str(uuid.uuid4()) if export_as == "pptx" else None
    export_url, fastapi_url = _build_presentation_export_url(
        presentation_id, cookie_header, chart_capture_token
    )
    name = (title or "").strip() or str(uuid.uuid4())
    export_result = await EXPORT_TASK_SERVICE.export_from_url(
        url=export_url,
        title=safe_export_basename(sanitize_filename(name)),
        export_as=export_as,
        fastapi_url=fastapi_url,
        cookie_header=cookie_header,
    )

    if export_as == "pptx" and chart_capture_token:
        try:
            await upgrade_flattened_charts_to_native(
                export_result.path, chart_capture_token, presentation_id
            )
        except Exception:
            LOGGER.exception(
                "presentation.export.native_chart_upgrade_failed",
            )

    log_memory(
        LOGGER,
        "presentation.export.finish",
        presentation_id=str(presentation_id),
        export_as=export_as,
    )
    return PresentationAndPath(
        presentation_id=presentation_id,
        path=export_result.path,
    )
