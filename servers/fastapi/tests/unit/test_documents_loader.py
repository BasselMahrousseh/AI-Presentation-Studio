import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image

from models.extraction_quality import VisualExtractability
from models.pptx_chart_data import ExtractedChart, ExtractedChartSeries, PptxStructuredData
from services.document_conversion_service import DocumentConversionService
from services.documents_loader import (
    DocumentsLoader,
    _classify_pptx_chart_flags,
    _detect_pdf_image_only_visuals,
    _merge_overlapping_image_boxes,
    _unwrap_liteparse_json_line_if_stored,
    clean_extracted_document_text,
)
from services.temp_file_service import TEMP_FILE_SERVICE


def test_unwrap_liteparse_json_line_extracts_text_field():
    inner_text = "Title\n\nBody with \"quotes\""
    payload = json.dumps({"ok": True, "filePath": "/tmp/test.pdf", "text": inner_text})

    assert _unwrap_liteparse_json_line_if_stored(payload) == inner_text
    assert _unwrap_liteparse_json_line_if_stored(f"  {payload}") == inner_text


def test_unwrap_liteparse_json_line_leaves_non_json_text():
    plain_text = "Not JSON, should stay as-is."
    assert _unwrap_liteparse_json_line_if_stored(plain_text) == plain_text


def test_clean_extracted_document_text_handles_malformed_json_body():
    malformed = (
        '{"ok": true, "filePath": "/tmp/test.pdf", "text": '
        '"hello\\nworld\\u0021 and trailing'
    )
    cleaned = clean_extracted_document_text(malformed)
    assert cleaned == "hello\nworld! and trailing"


def test_clean_extracted_document_text_unwraps_nested_liteparse_payloads():
    nested = json.dumps(
        {
            "ok": True,
            "filePath": "/tmp/outer.pdf",
            "text": json.dumps(
                {"ok": True, "filePath": "/tmp/inner.pdf", "text": "final body"}
            ),
        }
    )
    assert clean_extracted_document_text(nested) == "final body"


def test_load_pdf_requires_temp_dir_when_images_are_requested():
    loader = DocumentsLoader(file_paths=[])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            loader.load_pdf(
                file_path="/tmp/fake.pdf",
                load_text=False,
                load_images=True,
                temp_dir=None,
            )
        )

    assert exc.value.status_code == 400
    assert "temp_dir is required" in exc.value.detail


def test_convert_image_to_png_writes_png_file(tmp_path):
    source_path = tmp_path / "upload.jpg"
    output_dir = tmp_path / "converted"
    Image.new("RGB", (8, 8), "white").save(source_path, format="JPEG")

    converted_path = DocumentConversionService().convert_image_to_png(
        str(source_path),
        str(output_dir),
    )

    assert converted_path.endswith(".png")
    with Image.open(converted_path) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"


@patch("services.documents_loader.DocumentsLoader._parse_with_liteparse")
@patch("services.documents_loader.DocumentConversionService.convert_image_to_png")
def test_load_image_converts_to_png_before_ocr(mock_convert, mock_parse):
    mock_convert.return_value = "/tmp/converted.png"
    mock_parse.return_value = "image text"
    loader = DocumentsLoader(file_paths=[])

    result = loader.load_image("/tmp/upload.webp", "/tmp/conversions")

    assert result == "image text"
    mock_convert.assert_called_once_with(
        "/tmp/upload.webp",
        "/tmp/conversions",
        timeout_seconds=DocumentsLoader.DECOMPOSE_TIMEOUT_SECONDS,
    )
    mock_parse.assert_called_once_with("/tmp/converted.png", dpi=300)


@patch("services.documents_loader.DocumentsLoader.load_office_document")
def test_load_documents_parses_office_files_without_liteparse(
    mock_extract, tmp_path, monkeypatch
):
    managed_dir = tmp_path / "presenton-temp"
    managed_dir.mkdir()
    monkeypatch.setattr(TEMP_FILE_SERVICE, "base_dir", str(managed_dir))
    upload_dir = TEMP_FILE_SERVICE.create_temp_dir("upload-case")
    office_file = TEMP_FILE_SERVICE.create_temp_file("deck.pptx", b"pptx", upload_dir)
    mock_extract.return_value = "slide text"
    loader = DocumentsLoader(file_paths=[office_file])

    asyncio.run(loader.load_documents())

    assert loader.documents == ["slide text"]
    mock_extract.assert_called_once_with(office_file)


@patch("services.documents_loader.extract_pptx_structured_data")
@patch("services.documents_loader.DocumentsLoader.load_office_document")
def test_load_documents_appends_native_chart_data_for_pptx_sources(
    mock_extract_text, mock_extract_charts, tmp_path, monkeypatch
):
    managed_dir = tmp_path / "presenton-temp"
    managed_dir.mkdir()
    monkeypatch.setattr(TEMP_FILE_SERVICE, "base_dir", str(managed_dir))
    upload_dir = TEMP_FILE_SERVICE.create_temp_dir("upload-case")
    pptx_file = TEMP_FILE_SERVICE.create_temp_file("deck.pptx", b"pptx", upload_dir)
    mock_extract_text.return_value = "slide text"
    mock_extract_charts.return_value = PptxStructuredData(
        charts=[
            ExtractedChart(
                source_file="deck.pptx",
                slide_index=2,
                chart_part="ppt/charts/chart1.xml",
                title="Revenue",
                chart_type=None,
                raw_ooxml_type="barChart/col/clustered",
                categories=["North", "South"],
                series=[ExtractedChartSeries(name="2024", values=[42.0, 35.0])],
                extraction_method="chart_xml_cache",
                extractable=True,
            )
        ]
    )
    loader = DocumentsLoader(file_paths=[pptx_file])

    asyncio.run(loader.load_documents())

    assert loader.documents == [
        "slide text\n\n"
        '### Native chart data extracted from "deck.pptx" '
        "(exact values from the source file's embedded chart data — reuse verbatim, do not re-estimate)"
        "\n\n**Revenue** (slide 2) — barChart/col/clustered"
        "\nCategories: North, South"
        "\n- 2024: 42, 35"
    ]
    assert loader.structured_pptx_data[0].charts[0].extractable is True


@patch("services.documents_loader.extract_pptx_structured_data")
@patch("services.documents_loader.DocumentsLoader.load_office_document")
def test_load_documents_leaves_document_text_unchanged_when_no_charts_extractable(
    mock_extract_text, mock_extract_charts, tmp_path, monkeypatch
):
    managed_dir = tmp_path / "presenton-temp"
    managed_dir.mkdir()
    monkeypatch.setattr(TEMP_FILE_SERVICE, "base_dir", str(managed_dir))
    upload_dir = TEMP_FILE_SERVICE.create_temp_dir("upload-case")
    pptx_file = TEMP_FILE_SERVICE.create_temp_file("deck.pptx", b"pptx", upload_dir)
    mock_extract_text.return_value = "slide text"
    mock_extract_charts.return_value = PptxStructuredData(charts=[])

    loader = DocumentsLoader(file_paths=[pptx_file])
    asyncio.run(loader.load_documents())

    assert loader.documents == ["slide text"]


def _make_mock_page(text: str) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    return page


@patch("services.documents_loader.pdfplumber.open")
def test_is_scanned_pdf_returns_true_for_empty_pages(mock_open):
    mock_pdf = MagicMock()
    mock_pdf.pages = [_make_mock_page(""), _make_mock_page("")]
    mock_open.return_value.__enter__ = MagicMock(return_value=mock_pdf)
    mock_open.return_value.__exit__ = MagicMock(return_value=False)

    assert DocumentsLoader._is_scanned_pdf("/tmp/scanned.pdf") is True


@patch("services.documents_loader.pdfplumber.open")
def test_is_scanned_pdf_returns_false_for_text_pages(mock_open):
    mock_pdf = MagicMock()
    mock_pdf.pages = [
        _make_mock_page("Chapter 1: Introduction to calculus"),
        _make_mock_page("This chapter covers derivatives and integrals"),
    ]
    mock_open.return_value.__enter__ = MagicMock(return_value=mock_pdf)
    mock_open.return_value.__exit__ = MagicMock(return_value=False)

    assert DocumentsLoader._is_scanned_pdf("/tmp/text.pdf") is False


@patch("services.documents_loader.pdfplumber.open")
def test_is_scanned_pdf_threshold_edge_case(mock_open):
    mock_pdf = MagicMock()
    mock_pdf.pages = [_make_mock_page("x" * 49)]
    mock_open.return_value.__enter__ = MagicMock(return_value=mock_pdf)
    mock_open.return_value.__exit__ = MagicMock(return_value=False)

    assert DocumentsLoader._is_scanned_pdf("/tmp/edge.pdf", threshold=50) is True


@patch("services.documents_loader.pdfplumber.open")
def test_is_scanned_pdf_handles_exception_gracefully(mock_open):
    mock_open.side_effect = Exception("corrupt file")

    assert DocumentsLoader._is_scanned_pdf("/tmp/corrupt.pdf") is False


def test_merge_overlapping_image_boxes_merges_two_overlapping_rects():
    boxes = [(0, 0, 100, 100), (50, 50, 150, 150)]

    merged = _merge_overlapping_image_boxes(boxes)

    assert merged == [(0, 0, 150, 150)]


def test_merge_overlapping_image_boxes_merges_a_fully_nested_rect():
    outer = (585, 348, 859, 562)
    inner = (600, 364, 828, 544)

    merged = _merge_overlapping_image_boxes([outer, inner])

    assert merged == [outer]


def test_merge_overlapping_image_boxes_leaves_disjoint_rects_separate():
    boxes = [(0, 0, 10, 10), (900, 900, 910, 910)]

    merged = _merge_overlapping_image_boxes(boxes)

    assert sorted(merged) == sorted(boxes)


def test_merge_overlapping_image_boxes_chains_three_overlapping_rects():
    a = (0, 0, 60, 60)
    b = (50, 0, 120, 60)  # overlaps a
    c = (110, 0, 180, 60)  # overlaps b but not a directly

    merged = _merge_overlapping_image_boxes([a, b, c])

    assert merged == [(0, 0, 180, 60)]


def _image_box(x0, top, width, height):
    return {"x0": x0, "top": top, "x1": x0 + width, "bottom": top + height,
            "width": width, "height": height}


def _make_mock_page_with_image_boxes(page_number, width, height, images):
    page = MagicMock()
    page.page_number = page_number
    page.width = width
    page.height = height
    page.images = images
    return page


def _make_mock_page_with_images(page_number, width, height, image_boxes):
    # Places each image at a distinct, non-overlapping position by default -
    # callers that need overlapping boxes should build them with _image_box directly.
    images = [
        _image_box(x0=index * 1000, top=0, width=w, height=h)
        for index, (w, h) in enumerate(image_boxes)
    ]
    return _make_mock_page_with_image_boxes(page_number, width, height, images)


@patch("services.documents_loader.pdfplumber.open")
def test_detect_pdf_image_only_visuals_flags_large_images_only(mock_open):
    mock_pdf = MagicMock()
    mock_pdf.pages = [
        _make_mock_page_with_images(
            1,
            960,
            540,
            [
                (112, 49),  # a small logo - should not be flagged
                (900, 470),  # a near-full-page chart screenshot - should be flagged
            ],
        )
    ]
    mock_open.return_value.__enter__ = MagicMock(return_value=mock_pdf)
    mock_open.return_value.__exit__ = MagicMock(return_value=False)

    flags = _detect_pdf_image_only_visuals("/tmp/report.pdf")

    assert len(flags) == 1
    assert flags[0].location == "Page 1"
    assert flags[0].source_file == "report.pdf"
    assert flags[0].status == VisualExtractability.IMAGE_ONLY
    assert flags[0].visual_kind == "image"


@patch("services.documents_loader.pdfplumber.open")
def test_detect_pdf_image_only_visuals_merges_overlapping_images_before_thresholding(
    mock_open,
):
    """Regression test for a real gap found in the Ookla PDF: a chart rendered as
    a large background frame plus a smaller nested inset image. Neither the
    frame (11% of the page) nor the inset alone crossing 8% mattered here - what
    matters is that a *smaller* fragment that individually falls under the
    threshold must still be flagged when it overlaps a larger sibling image,
    since together they are one real chart a person would see as a single
    visual, not two independent decorative pictures.
    """
    mock_pdf = MagicMock()
    mock_pdf.pages = [
        _make_mock_page_with_image_boxes(
            1,
            960,
            540,
            [
                # A frame just above threshold...
                _image_box(x0=585, top=348, width=274, height=215),  # 11.36%
                # ...and a nested inset chart image that alone is just BELOW
                # threshold, fully contained inside the frame above.
                _image_box(x0=600, top=364, width=228, height=180),  # 7.90% alone
            ],
        )
    ]
    mock_open.return_value.__enter__ = MagicMock(return_value=mock_pdf)
    mock_open.return_value.__exit__ = MagicMock(return_value=False)

    flags = _detect_pdf_image_only_visuals("/tmp/report.pdf")

    # Merged into one flagged visual, not left as two separate un-flag-able
    # fragments and not double-counted as two flags for the same visual either.
    assert len(flags) == 1
    assert flags[0].location == "Page 1"


@patch("services.documents_loader.pdfplumber.open")
def test_detect_pdf_image_only_visuals_does_not_merge_non_overlapping_small_images(
    mock_open,
):
    mock_pdf = MagicMock()
    mock_pdf.pages = [
        _make_mock_page_with_image_boxes(
            1,
            960,
            540,
            [
                _image_box(x0=10, top=10, width=45, height=32),  # small icon
                _image_box(x0=900, top=500, width=45, height=32),  # unrelated small icon
            ],
        )
    ]
    mock_open.return_value.__enter__ = MagicMock(return_value=mock_pdf)
    mock_open.return_value.__exit__ = MagicMock(return_value=False)

    assert _detect_pdf_image_only_visuals("/tmp/report.pdf") == []


@patch("services.documents_loader.pdfplumber.open")
def test_detect_pdf_image_only_visuals_handles_exception_gracefully(mock_open):
    mock_open.side_effect = Exception("corrupt file")

    assert _detect_pdf_image_only_visuals("/tmp/corrupt.pdf") == []


def _extracted_chart(**overrides):
    defaults = dict(
        source_file="deck.pptx",
        slide_index=3,
        chart_part="ppt/charts/chart1.xml",
        title="Revenue",
        chart_type=None,
        raw_ooxml_type="barChart/col/clustered",
        categories=["North", "South"],
        series=[ExtractedChartSeries(name="2024", values=[42.0, 35.0])],
        extraction_method="chart_xml_cache",
        extractable=True,
    )
    defaults.update(overrides)
    return ExtractedChart(**defaults)


def test_classify_pptx_chart_flags_skips_fully_extracted_charts():
    from templates.v2.models.elements import ChartType

    data = PptxStructuredData(charts=[_extracted_chart(chart_type=ChartType.BAR)])

    assert _classify_pptx_chart_flags("deck.pptx", data) == []


def test_classify_pptx_chart_flags_flags_image_only_charts():
    data = PptxStructuredData(
        charts=[
            _extracted_chart(
                extractable=False, extraction_method="none", categories=[], series=[]
            )
        ]
    )

    flags = _classify_pptx_chart_flags("deck.pptx", data)

    assert len(flags) == 1
    assert flags[0].status == VisualExtractability.IMAGE_ONLY
    assert flags[0].location == "Slide 3"


def test_classify_pptx_chart_flags_flags_partial_for_missing_values_or_unmapped_type():
    data = PptxStructuredData(
        charts=[
            _extracted_chart(
                series=[ExtractedChartSeries(name="2024", values=[42.0, None])]
            )
        ]
    )

    flags = _classify_pptx_chart_flags("deck.pptx", data)

    assert len(flags) == 1
    assert flags[0].status == VisualExtractability.PARTIAL
    assert "chart type" in flags[0].detail
    assert "missing" in flags[0].detail


def test_classify_pptx_chart_flags_handles_none_structured_data():
    assert _classify_pptx_chart_flags("deck.pptx", None) == []
