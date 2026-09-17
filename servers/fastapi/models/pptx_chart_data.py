from typing import List, Literal, Optional

from pydantic import BaseModel

from templates.v2.models.elements import ChartType


class ExtractedChartSeries(BaseModel):
    name: str
    values: List[Optional[float]]


class ExtractedChart(BaseModel):
    source_file: str
    slide_index: Optional[int] = None
    chart_part: str
    title: Optional[str] = None
    chart_type: Optional[ChartType] = None
    raw_ooxml_type: str
    categories: List[str] = []
    series: List[ExtractedChartSeries] = []
    extraction_method: Literal["embedded_workbook", "chart_xml_cache", "none"] = "none"
    extractable: bool = False


class PptxStructuredData(BaseModel):
    charts: List[ExtractedChart] = []


def serialize_pptx_structured_data_for_llm(data: PptxStructuredData, source_file: str) -> str:
    """Render extracted native chart data as a labeled Markdown block for LLM context.

    Framed explicitly as ground truth so downstream prompts (which already instruct
    "preserve supplied data") reuse these exact numbers instead of re-estimating them.
    """
    extractable_charts = [chart for chart in data.charts if chart.extractable]
    if not extractable_charts:
        return ""

    lines = [
        f'### Native chart data extracted from "{source_file}" '
        "(exact values from the source file's embedded chart data — reuse verbatim, do not re-estimate)"
    ]
    for chart in extractable_charts:
        title = chart.title or "Untitled chart"
        chart_kind = chart.chart_type.value if chart.chart_type else chart.raw_ooxml_type
        location = f" (slide {chart.slide_index})" if chart.slide_index else ""
        lines.append(f"\n**{title}**{location} — {chart_kind}")
        if chart.categories:
            lines.append(f"Categories: {', '.join(chart.categories)}")
        for series in chart.series:
            values = ", ".join(
                "" if value is None else _format_number(value) for value in series.values
            )
            lines.append(f"- {series.name}: {values}")
    return "\n".join(lines)


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)
