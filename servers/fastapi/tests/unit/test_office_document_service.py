import io
import zipfile

import openpyxl
import pytest

from models.pptx_chart_data import ExtractedChartSeries
from services.office_document_service import (
    OfficeDocumentError,
    extract_office_document_text,
    extract_pptx_structured_data,
)
from templates.v2.models.elements import ChartType

_CHART_NS = (
    'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _write_zip(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _rels_xml(relationships):
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
        for rid, rtype, target in relationships
    )
    return (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{body}</Relationships>"
    )


def _bar_chart_xml(*, title="Revenue by Region", categories=None, series=None):
    categories = categories or ["North", "South"]
    series = series or [("2024", [42.0, 35.0])]

    cat_pts = "".join(
        f'<c:pt idx="{i}"><c:v>{value}</c:v></c:pt>' for i, value in enumerate(categories)
    )
    series_xml = ""
    for name, values in series:
        val_pts = "".join(
            f'<c:pt idx="{i}"><c:v>{value}</c:v></c:pt>' for i, value in enumerate(values)
        )
        series_xml += (
            "<c:ser>"
            f"<c:tx><c:strRef><c:f>Sheet1!$B$1</c:f><c:strCache><c:ptCount val=\"1\"/>"
            f'<c:pt idx="0"><c:v>{name}</c:v></c:pt></c:strCache></c:strRef></c:tx>'
            "<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$3</c:f>"
            f'<c:strCache><c:ptCount val="{len(categories)}"/>{cat_pts}</c:strCache>'
            "</c:strRef></c:cat>"
            "<c:val><c:numRef><c:f>Sheet1!$B$2:$B$3</c:f>"
            f'<c:numCache><c:ptCount val="{len(values)}"/>{val_pts}</c:numCache>'
            "</c:numRef></c:val>"
            "</c:ser>"
        )

    return (
        f"<c:chartSpace {_CHART_NS}><c:chart>"
        f"<c:title><c:tx><c:rich><a:p><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title>"
        "<c:plotArea><c:barChart><c:barDir val=\"col\"/><c:grouping val=\"clustered\"/>"
        f"{series_xml}"
        "</c:barChart></c:plotArea></c:chart>"
        '<c:externalData r:id="rId1"/></c:chartSpace>'
    )


def _make_workbook_bytes(rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_extracts_pptx_slide_text_in_slide_order(tmp_path):
    path = tmp_path / "deck.pptx"
    _write_zip(
        path,
        {
            "ppt/slides/slide10.xml": "<p:sld xmlns:p='p' xmlns:a='a'><a:t>Ten</a:t></p:sld>",
            "ppt/slides/slide2.xml": "<p:sld xmlns:p='p' xmlns:a='a'><a:t>Two</a:t></p:sld>",
            "ppt/slides/slide1.xml": "<p:sld xmlns:p='p' xmlns:a='a'><a:t>One</a:t></p:sld>",
        },
    )

    assert extract_office_document_text(str(path)) == "One\n\nTwo\n\nTen"


def test_extracts_docx_paragraphs(tmp_path):
    path = tmp_path / "document.docx"
    _write_zip(
        path,
        {
            "word/document.xml": (
                "<w:document xmlns:w='w'><w:body>"
                "<w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:t>world</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
        },
    )

    assert extract_office_document_text(str(path)) == "Hello world\nSecond paragraph"


def test_rejects_legacy_binary_office_formats(tmp_path):
    path = tmp_path / "legacy.ppt"
    path.write_bytes(b"legacy")

    with pytest.raises(OfficeDocumentError, match="external office conversion engine"):
        extract_office_document_text(str(path))


def test_extracts_native_chart_data_from_cache_when_no_workbook_present(tmp_path):
    path = tmp_path / "deck.pptx"
    _write_zip(
        path,
        {
            "ppt/slides/slide1.xml": "<p:sld xmlns:p='p' xmlns:a='a'/>",
            "ppt/slides/_rels/slide1.xml.rels": _rels_xml(
                [
                    (
                        "rId1",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
                        "../charts/chart1.xml",
                    )
                ]
            ),
            "ppt/charts/chart1.xml": _bar_chart_xml(
                categories=["North", "South"], series=[("2024 Revenue", [42.0, 35.0])]
            ),
        },
    )

    data = extract_pptx_structured_data(str(path))

    assert len(data.charts) == 1
    chart = data.charts[0]
    assert chart.extractable is True
    assert chart.extraction_method == "chart_xml_cache"
    assert chart.chart_type == ChartType.BAR
    assert chart.slide_index == 1
    assert chart.title == "Revenue by Region"
    assert chart.categories == ["North", "South"]
    assert chart.series == [ExtractedChartSeries(name="2024 Revenue", values=[42.0, 35.0])]


def test_prefers_embedded_workbook_values_over_stale_cache(tmp_path):
    path = tmp_path / "deck.pptx"
    workbook_bytes = _make_workbook_bytes(
        [
            ["Region", "2024 Revenue"],
            ["North", 99.0],
            ["South", 88.0],
        ]
    )
    _write_zip(
        path,
        {
            "ppt/charts/chart1.xml": _bar_chart_xml(
                categories=["North", "South"], series=[("2024 Revenue", [42.0, 35.0])]
            ),
            "ppt/charts/_rels/chart1.xml.rels": _rels_xml(
                [
                    (
                        "rId1",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package",
                        "../embeddings/workbook.xlsx",
                    )
                ]
            ),
            "ppt/embeddings/workbook.xlsx": workbook_bytes,
        },
    )

    data = extract_pptx_structured_data(str(path))

    chart = data.charts[0]
    assert chart.extraction_method == "embedded_workbook"
    assert chart.series[0].values == [99.0, 88.0]


def test_horizontal_stacked_bar_type_detected_from_bar_dir_and_grouping(tmp_path):
    path = tmp_path / "deck.pptx"
    chart_xml = _bar_chart_xml().replace(
        '<c:barDir val="col"/><c:grouping val="clustered"/>',
        '<c:barDir val="bar"/><c:grouping val="stacked"/>',
    )
    _write_zip(path, {"ppt/charts/chart1.xml": chart_xml})

    data = extract_pptx_structured_data(str(path))

    assert data.charts[0].chart_type == ChartType.HORIZONTAL_STACKED_BAR


def test_multi_level_categories_are_flattened_and_forward_filled(tmp_path):
    chart_xml = (
        f"<c:chartSpace {_CHART_NS}><c:chart><c:plotArea><c:lineChart>"
        "<c:ser>"
        "<c:tx><c:strRef><c:strCache><c:ptCount val=\"1\"/>"
        '<c:pt idx="0"><c:v>Du</c:v></c:pt></c:strCache></c:strRef></c:tx>'
        "<c:cat><c:multiLvlStrRef><c:multiLvlStrCache><c:ptCount val=\"4\"/>"
        '<c:lvl><c:pt idx="0"><c:v>Jan</c:v></c:pt><c:pt idx="1"><c:v>Feb</c:v></c:pt>'
        '<c:pt idx="2"><c:v>Jan</c:v></c:pt><c:pt idx="3"><c:v>Feb</c:v></c:pt></c:lvl>'
        '<c:lvl><c:pt idx="0"><c:v>Singapore</c:v></c:pt>'
        '<c:pt idx="2"><c:v>Chile</c:v></c:pt></c:lvl>'
        "</c:multiLvlStrCache></c:multiLvlStrRef></c:cat>"
        "<c:val><c:numRef><c:numCache><c:ptCount val=\"4\"/>"
        '<c:pt idx="0"><c:v>10</c:v></c:pt><c:pt idx="1"><c:v>11</c:v></c:pt>'
        '<c:pt idx="2"><c:v>20</c:v></c:pt><c:pt idx="3"><c:v>21</c:v></c:pt>'
        "</c:numCache></c:numRef></c:val>"
        "</c:ser>"
        "</c:lineChart></c:plotArea></c:chart></c:chartSpace>"
    )
    path = tmp_path / "deck.pptx"
    _write_zip(path, {"ppt/charts/chart1.xml": chart_xml})

    data = extract_pptx_structured_data(str(path))

    chart = data.charts[0]
    assert chart.extractable is True
    assert chart.categories == ["Singapore / Jan", "Singapore / Feb", "Chile / Jan", "Chile / Feb"]
    assert chart.series[0].values == [10.0, 11.0, 20.0, 21.0]


def test_chart_with_no_plot_area_is_reported_as_unextractable(tmp_path):
    path = tmp_path / "deck.pptx"
    _write_zip(
        path,
        {"ppt/charts/chart1.xml": f"<c:chartSpace {_CHART_NS}><c:chart/></c:chartSpace>"},
    )

    data = extract_pptx_structured_data(str(path))

    assert data.charts[0].extractable is False
    assert data.charts[0].extraction_method == "none"


def test_categories_are_padded_to_match_the_widest_series_cached_count(tmp_path):
    # Series 1 has a 2-point cache for both categories and values; series 2's cache (a
    # partially-stale chart, a real pattern this app has hit in production) reports 3 cached
    # value points while its own category reference cache is still stuck at 2. Every series'
    # values list and chart.categories must come out the same length, or
    # document_fact_dedup_service.py's zip(chart.categories, series.values) silently
    # truncates/mispairs data.
    chart_xml = (
        f"<c:chartSpace {_CHART_NS}><c:chart><c:plotArea><c:barChart>"
        '<c:barDir val="col"/><c:grouping val="clustered"/>'
        "<c:ser>"
        "<c:tx><c:strRef><c:strCache><c:ptCount val=\"1\"/>"
        '<c:pt idx="0"><c:v>S1</c:v></c:pt></c:strCache></c:strRef></c:tx>'
        "<c:cat><c:strRef><c:strCache><c:ptCount val=\"2\"/>"
        '<c:pt idx="0"><c:v>A</c:v></c:pt><c:pt idx="1"><c:v>B</c:v></c:pt>'
        "</c:strCache></c:strRef></c:cat>"
        "<c:val><c:numRef><c:numCache><c:ptCount val=\"2\"/>"
        '<c:pt idx="0"><c:v>1</c:v></c:pt><c:pt idx="1"><c:v>2</c:v></c:pt>'
        "</c:numCache></c:numRef></c:val>"
        "</c:ser>"
        "<c:ser>"
        "<c:tx><c:strRef><c:strCache><c:ptCount val=\"1\"/>"
        '<c:pt idx="0"><c:v>S2</c:v></c:pt></c:strCache></c:strRef></c:tx>'
        "<c:cat><c:strRef><c:strCache><c:ptCount val=\"2\"/>"
        '<c:pt idx="0"><c:v>A</c:v></c:pt><c:pt idx="1"><c:v>B</c:v></c:pt>'
        "</c:strCache></c:strRef></c:cat>"
        "<c:val><c:numRef><c:numCache><c:ptCount val=\"3\"/>"
        '<c:pt idx="0"><c:v>10</c:v></c:pt><c:pt idx="1"><c:v>20</c:v></c:pt>'
        '<c:pt idx="2"><c:v>30</c:v></c:pt>'
        "</c:numCache></c:numRef></c:val>"
        "</c:ser>"
        "</c:barChart></c:plotArea></c:chart></c:chartSpace>"
    )
    path = tmp_path / "deck.pptx"
    _write_zip(path, {"ppt/charts/chart1.xml": chart_xml})

    data = extract_pptx_structured_data(str(path))

    chart = data.charts[0]
    assert len(chart.categories) == 3
    for series in chart.series:
        assert len(series.values) == len(chart.categories)
    assert chart.categories == ["A", "B", ""]
    assert chart.series[0].values == [1.0, 2.0, None]
    assert chart.series[1].values == [10.0, 20.0, 30.0]


def test_chart_with_all_none_values_is_not_reported_as_extractable(tmp_path):
    chart_xml = (
        f"<c:chartSpace {_CHART_NS}><c:chart><c:plotArea><c:barChart>"
        '<c:barDir val="col"/><c:grouping val="clustered"/>'
        "<c:ser>"
        "<c:cat><c:strRef><c:strCache><c:ptCount val=\"2\"/>"
        "</c:strCache></c:strRef></c:cat>"
        "<c:val><c:numRef><c:numCache><c:ptCount val=\"2\"/>"
        "</c:numCache></c:numRef></c:val>"
        "</c:ser>"
        "</c:barChart></c:plotArea></c:chart></c:chartSpace>"
    )
    path = tmp_path / "deck.pptx"
    _write_zip(path, {"ppt/charts/chart1.xml": chart_xml})

    data = extract_pptx_structured_data(str(path))

    chart = data.charts[0]
    assert chart.series[0].values == [None, None]
    assert chart.extractable is False
    assert chart.extraction_method == "none"


def test_extract_pptx_structured_data_returns_empty_for_non_pptx_zip(tmp_path):
    path = tmp_path / "not-a-pptx.zip"
    _write_zip(path, {"readme.txt": "hi"})

    assert extract_pptx_structured_data(str(path)).charts == []
