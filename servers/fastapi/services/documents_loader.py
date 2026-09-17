import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pdfplumber
from fastapi import HTTPException

from constants.documents import (
    IMAGE_EXTENSIONS,
    OFFICE_EXTENSIONS,
    PDF_EXTENSIONS,
    TEXT_EXTENSIONS,
)
from services.document_conversion_service import (
    DocumentConversionError,
    DocumentConversionService,
)
from services.liteparse_service import LiteParseError, LiteParseService
from models.extraction_quality import VisualExtractability, VisualQualityFlag
from models.pptx_chart_data import PptxStructuredData, serialize_pptx_structured_data_for_llm
from services.office_document_service import (
    OfficeDocumentError,
    extract_office_document_text,
    extract_pptx_structured_data,
)
from services.temp_file_service import TEMP_FILE_SERVICE
from utils.ocr_language import presentation_language_to_ocr_code

# Optional fallback converter (primarily useful on Windows)
try:
    from services.lightweight_document_service import DocumentService as DocumentServiceCls
except Exception:
    DocumentServiceCls = None

LOGGER = logging.getLogger(__name__)


def _unwrap_liteparse_json_line_if_stored(text: str) -> str:
    """If the whole JSON line from the LiteParse runner was stored as the document, keep only the text field."""
    if not text:
        return text
    s = text.lstrip()
    if not s.startswith("{"):
        return text
    try:
        payload = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return text
    if not isinstance(payload, dict):
        return text
    if (
        payload.get("ok") is True
        and "filePath" in payload
        and isinstance(payload.get("text"), str)
    ):
        return payload["text"]
    return text


# A source PDF's embedded picture is only worth flagging as a likely chart/table
# (as opposed to a logo/icon) once it covers a meaningful share of the page - this
# is a judgment call, calibrated against a real report where charts/tables covered
# 85%+ of the page and logos covered 1-2%; adjust if real usage shows otherwise.
_PDF_LARGE_IMAGE_AREA_RATIO = 0.08

_RE_TEXT_KEY = re.compile(r'"text"\s*:\s*"')


def _json_unescape_quoted_value(s: str, content_start: int) -> str:
    """
    Unescape a JSON string value. `content_start` is the index of the first character
    *inside* the value (immediately after the opening quote of the "text" field).
    If the closing quote is missing (truncated), returns the unescaped rest of the string.
    """
    out: list[str] = []
    i = content_start
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            e = s[i + 1]
            if e in '"\\':
                out.append(e)
                i += 2
            elif e == "/":
                out.append("/")
                i += 2
            elif e == "b":
                out.append("\b")
                i += 2
            elif e == "f":
                out.append("\f")
                i += 2
            elif e == "n":
                out.append("\n")
                i += 2
            elif e == "r":
                out.append("\r")
                i += 2
            elif e == "t":
                out.append("\t")
                i += 2
            elif e == "u" and i + 5 < n:
                try:
                    out.append(chr(int(s[i + 2 : i + 6], 16)))
                except (ValueError, OverflowError):
                    out.append(s[i : i + 6])
                i += 6
            else:
                out.append(e)
                i += 2
        elif c == '"':
            return "".join(out)
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _try_extract_liteparse_text_value_from_malformed_json(s: str) -> Optional[str]:
    """
    When json.loads failed (e.g. truncated or corrupt), find the "text" field value
    in a LiteParse-shaped object and return only the unescaped string body.
    """
    if not s.startswith("{"):
        return None
    head = s[:10000] if len(s) > 10000 else s
    if not ("ok" in head and "filePath" in head):
        return None
    m = _RE_TEXT_KEY.search(s)
    if not m:
        return None
    return _json_unescape_quoted_value(s, m.end())


def _clean_extracted_one_pass(t: str) -> str:
    for _ in range(3):
        nxt = _unwrap_liteparse_json_line_if_stored(t)
        if nxt == t:
            break
        t = nxt
    s = t.lstrip()
    if s.startswith("{"):
        m = _try_extract_liteparse_text_value_from_malformed_json(s)
        if m is not None:
            return m
    return t


def clean_extracted_document_text(text: str) -> str:
    """
    Return only the document body: strip LiteParse JSON wrappers, then drop any
    leading payload before the "text" value (handles truncated/invalid JSON).
    Multiple passes in case the inner body is again JSON-shaped.
    """
    if not text:
        return text
    t = text
    for _ in range(4):
        nxt = _clean_extracted_one_pass(t)
        if nxt == t:
            return t
        t = nxt
    return t


def _classify_pptx_chart_flags(
    source_file: str, structured_data: Optional[PptxStructuredData]
) -> List[VisualQualityFlag]:
    """Turn item 1's extraction results into review flags.

    A fully, cleanly extracted chart produces no flag at all - only a chart with
    no recoverable data (IMAGE_ONLY) or an incomplete recovery (PARTIAL, e.g. some
    missing data points or an unmapped chart type) needs a person to look at it.
    """
    if structured_data is None:
        return []

    flags: List[VisualQualityFlag] = []
    for chart in structured_data.charts:
        location = f"Slide {chart.slide_index}" if chart.slide_index else "Unknown slide"
        label = chart.title or chart.chart_part

        if not chart.extractable:
            flags.append(
                VisualQualityFlag(
                    source_file=source_file,
                    location=location,
                    visual_label=label,
                    visual_kind="chart",
                    status=VisualExtractability.IMAGE_ONLY,
                    detail="This chart's underlying data could not be read from the file.",
                    recommendation=(
                        "Request the original data behind this chart, or rebuild it "
                        "manually in the generated deck."
                    ),
                )
            )
            continue

        has_missing_values = any(
            value is None for series in chart.series for value in series.values
        )
        if chart.chart_type is None or has_missing_values:
            reasons = []
            if chart.chart_type is None:
                reasons.append("its chart type couldn't be matched to a supported kind")
            if has_missing_values:
                reasons.append("some data points are missing")
            flags.append(
                VisualQualityFlag(
                    source_file=source_file,
                    location=location,
                    visual_label=label,
                    visual_kind="chart",
                    status=VisualExtractability.PARTIAL,
                    detail="Partially recovered — " + " and ".join(reasons) + ".",
                    recommendation="Double-check this chart's values before relying on them.",
                )
            )
    return flags


_ImageBox = tuple[float, float, float, float]


def _boxes_overlap(a: _ImageBox, b: _ImageBox) -> bool:
    ax0, atop, ax1, abottom = a
    bx0, btop, bx1, bbottom = b
    return ax0 < bx1 and bx0 < ax1 and atop < bbottom and btop < abottom


def _merge_overlapping_image_boxes(boxes: List[_ImageBox]) -> List[_ImageBox]:
    """Union-find merge of overlapping/nested image boxes on one page.

    A single chart is sometimes composed of more than one overlapping raster
    image (e.g. a background frame plus a nested inset/zoomed-in chart) -
    measuring each image's page-area share independently can let a real
    chart's smaller fragment fall under the size threshold even though the
    combined visual a person actually sees is clearly a large chart. Merging
    first measures the same physical visual a reader would see, rather than
    whichever individual XObject happens to be biggest.
    """
    n = len(boxes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    for i in range(n):
        for j in range(i + 1, n):
            if _boxes_overlap(boxes[i], boxes[j]):
                union(i, j)

    groups: dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    merged: List[_ImageBox] = []
    for indices in groups.values():
        x0 = min(boxes[i][0] for i in indices)
        top = min(boxes[i][1] for i in indices)
        x1 = max(boxes[i][2] for i in indices)
        bottom = max(boxes[i][3] for i in indices)
        merged.append((x0, top, x1, bottom))
    return merged


def _detect_pdf_image_only_visuals(file_path: str) -> List[VisualQualityFlag]:
    """Flag large embedded pictures in a source PDF as no-data-recoverable.

    No existing or reasonably buildable parser can recover a chart/table's real
    series data from a PDF that only ever retained the rendered picture - this
    surfaces that limitation instead of silently dropping or approximating it.
    """
    source_file = os.path.basename(file_path)
    flags: List[VisualQualityFlag] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_area = float(page.width or 0) * float(page.height or 0)
                if page_area <= 0:
                    continue
                boxes: List[_ImageBox] = []
                for image in page.images:
                    width = float(image.get("width") or 0)
                    height = float(image.get("height") or 0)
                    if width <= 0 or height <= 0:
                        continue
                    boxes.append(
                        (image["x0"], image["top"], image["x1"], image["bottom"])
                    )
                for x0, top, x1, bottom in _merge_overlapping_image_boxes(boxes):
                    area = (x1 - x0) * (bottom - top)
                    if area / page_area < _PDF_LARGE_IMAGE_AREA_RATIO:
                        continue
                    flags.append(
                        VisualQualityFlag(
                            source_file=source_file,
                            location=f"Page {page.page_number}",
                            visual_label=None,
                            visual_kind="image",
                            status=VisualExtractability.IMAGE_ONLY,
                            detail=(
                                "A large embedded image (likely a chart or table) with no "
                                "extractable underlying data — the source PDF only retains "
                                "the rendered picture, not the numbers behind it."
                            ),
                            recommendation=(
                                "Request the original data export, or keep this as a "
                                "static image in the generated deck."
                            ),
                        )
                    )
    except Exception:
        LOGGER.warning(
            "[DocumentsLoader] Failed to scan %s for large embedded images",
            file_path,
            exc_info=True,
        )
    return flags


class DocumentsLoader:
    DECOMPOSE_TIMEOUT_SECONDS = 600

    def __init__(
        self,
        file_paths: List[str],
        presentation_language: Optional[str] = None,
    ):
        self._file_paths = TEMP_FILE_SERVICE.resolve_existing_temp_paths(file_paths)
        self._ocr_language = presentation_language_to_ocr_code(presentation_language)
        self.liteparse_service = LiteParseService(
            timeout_seconds=self.DECOMPOSE_TIMEOUT_SECONDS
        )
        self.document_conversion_service = DocumentConversionService()
        self.document_service: Any = (
            DocumentServiceCls() if DocumentServiceCls is not None else None
        )

        self._documents: List[str] = []
        self._images: List[List[str]] = []
        self._structured_pptx_data: List[Optional[PptxStructuredData]] = []
        self._quality_flags: List[VisualQualityFlag] = []

    @property
    def documents(self):
        return self._documents

    @property
    def images(self):
        return self._images

    @property
    def structured_pptx_data(self):
        return self._structured_pptx_data

    @property
    def quality_flags(self):
        return self._quality_flags

    async def load_documents(
        self,
        temp_dir: Optional[str] = None,
        load_text: bool = True,
        load_images: bool = False,
    ):
        """If load_images is True, temp_dir must be provided"""

        documents: List[str] = []
        images: List[List[str]] = []
        structured_pptx_data: List[Optional[PptxStructuredData]] = []
        quality_flags: List[VisualQualityFlag] = []

        for file_path in self._file_paths:
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=404, detail=f"File {file_path} not found"
                )

            document = ""
            imgs: List[str] = []
            structured_data: Optional[PptxStructuredData] = None

            extension = Path(file_path).suffix.lower()
            LOGGER.info(
                "[DocumentsLoader] Processing file=%s extension=%s",
                file_path,
                extension,
            )

            if extension in PDF_EXTENSIONS:
                document, imgs = await self.load_pdf(
                    file_path, load_text, load_images, temp_dir
                )
                if load_text:
                    quality_flags.extend(
                        await asyncio.to_thread(_detect_pdf_image_only_visuals, file_path)
                    )
            elif extension in TEXT_EXTENSIONS:
                document = await self.load_text(file_path)
            elif extension in OFFICE_EXTENSIONS:
                document = await asyncio.to_thread(
                    self.load_office_document,
                    file_path,
                )
                if extension in {".pptx", ".pptm"}:
                    structured_data = await asyncio.to_thread(
                        self._load_pptx_structured_data,
                        file_path,
                    )
                    if structured_data is not None:
                        chart_block = serialize_pptx_structured_data_for_llm(
                            structured_data, os.path.basename(file_path)
                        )
                        if chart_block:
                            document = f"{document}\n\n{chart_block}" if document else chart_block
                    quality_flags.extend(
                        _classify_pptx_chart_flags(os.path.basename(file_path), structured_data)
                    )
            elif extension in IMAGE_EXTENSIONS:
                document = await asyncio.to_thread(
                    self.load_image,
                    file_path,
                    temp_dir,
                )
            else:
                document = await asyncio.to_thread(self._parse_with_liteparse, file_path)

            document = clean_extracted_document_text(document)
            documents.append(document)
            images.append(imgs)
            structured_pptx_data.append(structured_data)

        self._documents = documents
        self._images = images
        self._structured_pptx_data = structured_pptx_data
        self._quality_flags = quality_flags

    @staticmethod
    def _load_pptx_structured_data(file_path: str) -> Optional[PptxStructuredData]:
        try:
            return extract_pptx_structured_data(file_path)
        except Exception:
            LOGGER.warning(
                "[DocumentsLoader] Failed to extract native chart data file=%s",
                file_path,
                exc_info=True,
            )
            return None

    async def load_pdf(
        self,
        file_path: str,
        load_text: bool,
        load_images: bool,
        temp_dir: Optional[str] = None,
    ) -> Tuple[str, List[str]]:
        image_paths: List[str] = []
        document: str = ""

        if load_text:
            is_scanned = await asyncio.to_thread(self._is_scanned_pdf, file_path)
            dpi = 300 if is_scanned else None
            document = await asyncio.to_thread(self._parse_with_liteparse, file_path, dpi)

        if load_images:
            if temp_dir is None:
                raise HTTPException(
                    status_code=400,
                    detail="temp_dir is required when load_images is true",
                )
            image_paths = await self.get_page_images_from_pdf_async(file_path, temp_dir)

        return document, image_paths

    @staticmethod
    def _is_scanned_pdf(file_path: str, sample_pages: int = 5, threshold: int = 50) -> bool:
        """Check if a PDF is scanned (image-only) by sampling pages for text content."""
        try:
            with pdfplumber.open(file_path) as pdf:
                total_chars = 0
                for i, page in enumerate(pdf.pages[:sample_pages]):
                    text = page.extract_text() or ""
                    total_chars += len(text.strip())
                return total_chars < threshold
        except Exception:
            return False

    async def load_text(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as file:
            return await asyncio.to_thread(file.read)

    @staticmethod
    def load_office_document(file_path: str) -> str:
        try:
            return extract_office_document_text(file_path)
        except OfficeDocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def load_image(self, file_path: str, temp_dir: Optional[str] = None) -> str:
        if temp_dir:
            converted_path = self.document_conversion_service.convert_image_to_png(
                file_path,
                temp_dir,
                timeout_seconds=self.DECOMPOSE_TIMEOUT_SECONDS,
            )
            return self._parse_with_liteparse(converted_path, dpi=300)

        with tempfile.TemporaryDirectory(prefix="image-convert-") as conversion_dir:
            converted_path = self.document_conversion_service.convert_image_to_png(
                file_path,
                conversion_dir,
                timeout_seconds=self.DECOMPOSE_TIMEOUT_SECONDS,
            )
            return self._parse_with_liteparse(converted_path, dpi=300)

    def _parse_with_liteparse(self, file_path: str, dpi: int = None) -> str:
        try:
            LOGGER.info("[DocumentsLoader] LiteParse start file=%s", file_path)
            return self.liteparse_service.parse_to_markdown(
                file_path,
                ocr_enabled=True,
                ocr_language=self._ocr_language,
                dpi=dpi,
            )
        except (LiteParseError, DocumentConversionError, OfficeDocumentError) as exc:
            LOGGER.warning(
                "[DocumentsLoader] Primary parse failed file=%s error=%s",
                file_path,
                exc,
            )
            if self.document_service is not None:
                try:
                    LOGGER.info("[DocumentsLoader] Trying fallback parser file=%s", file_path)
                    return self.document_service.parse_to_markdown(file_path)
                except Exception:
                    LOGGER.exception(
                        "[DocumentsLoader] Fallback parser failed file=%s",
                        file_path,
                    )
                    pass
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse document {os.path.basename(file_path)}: {exc}",
            ) from exc

    @classmethod
    def get_page_images_from_pdf(cls, file_path: str, temp_dir: str) -> List[str]:
        with pdfplumber.open(file_path) as pdf:
            images = []
            for page in pdf.pages:
                img = page.to_image(resolution=150)
                image_path = os.path.join(temp_dir, f"page_{page.page_number}.png")
                img.save(image_path)
                images.append(image_path)
            return images

    @classmethod
    async def get_page_images_from_pdf_async(cls, file_path: str, temp_dir: str):
        return await asyncio.to_thread(
            cls.get_page_images_from_pdf, file_path, temp_dir
        )
