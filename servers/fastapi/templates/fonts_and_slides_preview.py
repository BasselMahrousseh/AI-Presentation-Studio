import html
import secrets
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from fastapi import HTTPException

from utils.asset_directory_utils import (
    absolute_fastapi_asset_url,
)
from utils.smart_preview_safety import sanitize_slide_preview_html, TRUSTED_CHART_INITIALIZER


FontInfoData = Tuple[str, Optional[str]] | Tuple[str, Optional[str], List[str]]


PREVIEW_WIDTH = 1280
PREVIEW_HEIGHT = 720
TAILWIND_BROWSER_SCRIPT_PATH = "/static/vendor/tailwindcss-browser-4.3.3.js"
CHART_JS_SCRIPT_PATH = "/static/vendor/chart-4.5.1.umd.min.js"
CHART_DATALABELS_SCRIPT_PATH = (
    "/static/vendor/chartjs-plugin-datalabels-2.2.0.min.js"
)
MAX_TEMPLATE_PREVIEW_SLIDES = 50
MAX_FONT_CHECK_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024
FONT_CHECK_UPLOAD_SIZE_ERROR = "File size must be less than 100MB."
INVALID_PPTX_UPLOAD_ERROR = (
    "The uploaded PowerPoint file is corrupted or unsupported."
)
PPT_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("p", PPT_NS["p"])
ET.register_namespace("r", PPT_NS["r"])


def _chart_js_url() -> str:
    return absolute_fastapi_asset_url(CHART_JS_SCRIPT_PATH)


def _chart_datalabels_url() -> str:
    return absolute_fastapi_asset_url(CHART_DATALABELS_SCRIPT_PATH)


def _build_slide_preview_html(
    slide_html: str,
    font_css: str,
    font_links: str = "",
    width: int = PREVIEW_WIDTH,
    height: int = PREVIEW_HEIGHT,
    background: str = "#ffffff",
    extra_css: str = "",
) -> str:
    fastapi_base = absolute_fastapi_asset_url("/").rstrip("/") + "/"
    tailwind_browser_url = absolute_fastapi_asset_url(
        TAILWIND_BROWSER_SCRIPT_PATH
    )
    slide_html = sanitize_slide_preview_html(slide_html)
    nonce = secrets.token_urlsafe(18)
    content_policy = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; "
        "style-src 'unsafe-inline' http: https:; img-src data: http: https:; "
        "font-src data: http: https:; connect-src 'none'; object-src 'none'; "
        "frame-src 'none'; form-action 'none'; base-uri http: https:"
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="{html.escape(content_policy, quote=True)}" />
  <base href="{fastapi_base}" />
  <script nonce="{nonce}" src="{html.escape(tailwind_browser_url, quote=True)}"></script>
  <script nonce="{nonce}" src="{html.escape(_chart_js_url(), quote=True)}"></script>
  <script nonce="{nonce}" src="{html.escape(_chart_datalabels_url(), quote=True)}"></script>
  {font_links}
  <style>
    html,
    body {{
      width: {width}px;
      height: {height}px;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: {background};
    }}

    *,
    *::before,
    *::after {{
      box-sizing: border-box;
    }}

    #slide-preview-root {{
      position: relative;
      width: {width}px;
      height: {height}px;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: {background};
    }}

    .slide-container {{
      width: {width}px;
      height: {height}px;
      margin: 0;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      overflow: hidden;
    }}

    .slide-content {{
      position: relative;
      width: {width}px;
      height: {height}px;
      margin: 0;
      flex: 0 0 auto;
      overflow: hidden;
      box-shadow: none;
    }}

    img,
    svg,
    video,
    canvas {{
      max-width: none;
    }}

    {font_css or ""}

    {extra_css or ""}
  </style>
</head>
<body>
  <div id="slide-preview-root">{slide_html}</div>
  <script nonce="{nonce}">{TRUSTED_CHART_INITIALIZER}</script>
</body>
</html>"""


def _write_bytes_to_path(path: str, data: bytes) -> None:
    with open(path, "wb") as file:
        file.write(data)


def _raise_if_font_check_upload_too_large(size: int | None) -> None:
    if size is not None and size >= MAX_FONT_CHECK_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=FONT_CHECK_UPLOAD_SIZE_ERROR)


def _validate_pptx_package(pptx_path: str) -> None:
    try:
        with zipfile.ZipFile(pptx_path, "r") as archive:
            bad_member = archive.testzip()
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=INVALID_PPTX_UPLOAD_ERROR,
        ) from exc

    has_slide = any(
        name.startswith("ppt/slides/slide") and name.endswith(".xml")
        for name in names
    )
    if (
        bad_member
        or "[Content_Types].xml" not in names
        or "ppt/presentation.xml" not in names
        or not has_slide
    ):
        raise HTTPException(status_code=400, detail=INVALID_PPTX_UPLOAD_ERROR)


