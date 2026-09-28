from __future__ import annotations

import math
import re
from typing import Any


def _chart_element_has_explicit_data(element: dict[str, Any]) -> bool:
    return bool(
        _normalize_chart_series(
            element.get("series"),
            fallback_name=str(element.get("title") or "Series 1"),
        )
        or _normalize_legacy_chart_data(element.get("data"))
    )


def _table_element_has_explicit_data(element: dict[str, Any]) -> bool:
    columns = element.get("columns")
    headers = element.get("headers")
    rows = element.get("rows")
    has_columns = isinstance(columns, list) and len(columns) > 0
    has_headers = isinstance(headers, list) and len(headers) > 0
    has_rows = isinstance(rows, list) and len(rows) > 0
    return (has_columns or has_headers) and has_rows


def _image_element_has_explicit_data(element: dict[str, Any]) -> bool:
    asset_url = _template_asset_url(element)
    return bool(asset_url and _looks_like_asset_reference(asset_url))


def _normalize_chart_series(
    value: Any,
    *,
    fallback_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    series: list[dict[str, Any]] = []
    for index, item in enumerate(value[:20]):
        if isinstance(item, dict):
            raw_values = item.get("values")
            if not isinstance(raw_values, list):
                raw_values = item.get("data")
            if not isinstance(raw_values, list):
                continue
            name = item.get("name")
            series_name = (
                str(name).strip()
                if isinstance(name, str) and name.strip()
                else fallback_name
                if index == 0 and fallback_name
                else f"Series {index + 1}"
            )
        elif isinstance(item, list):
            raw_values = item
            series_name = (
                fallback_name
                if index == 0 and fallback_name
                else f"Series {index + 1}"
            )
        else:
            continue

        values = [
            number
            for raw_value in raw_values[:100]
            if (number := _chart_number(raw_value)) is not None
        ]
        if values:
            series.append({"name": series_name, "values": values})
    return series


def _chart_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        number = float(value)
        return int(number) if number.is_integer() else number
    if isinstance(value, str):
        match = re.search(
            r"[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?",
            value.strip(),
        )
        if not match:
            return None
        try:
            number = float(match.group(0).replace(",", ""))
        except ValueError:
            return None
        if math.isfinite(number):
            return int(number) if number.is_integer() else number
    return None


def _normalize_legacy_chart_data(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in value[:100]:
        direct_number = _chart_number(item)
        if direct_number is not None:
            rows.append({"label": "", "value": direct_number})
            continue

        if not isinstance(item, dict):
            continue
        number = _first_chart_number(item.get("value"), item.get("data"), item.get("y"))
        if number is None:
            continue

        row: dict[str, Any] = {
            "label": _first_chart_label(
                item.get("label"),
                item.get("name"),
                item.get("category"),
                item.get("x"),
            ),
            "value": number,
        }
        color = _normalize_chart_color(item.get("color"))
        if color:
            row["color"] = color
        rows.append(row)
    return rows


def _first_chart_number(*values: Any) -> float | int | None:
    for value in values:
        number = _chart_number(value)
        if number is not None:
            return number
    return None


def _first_chart_label(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        label = str(value).strip()
        if label:
            return label
    return ""


def _normalize_chart_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    color = value.strip()
    if not color:
        return None
    hex_match = re.match(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", color)
    if hex_match:
        raw = hex_match.group(1)
        if len(raw) == 3:
            raw = "".join(char + char for char in raw)
        return f"#{raw.upper()}"
    if re.match(r"^rgba?\([^)]+\)$", color, re.IGNORECASE):
        return color
    return color


def _snippet(text: str, query: str, limit: int = 220) -> str:
    normalized = text.replace("\n", " ")
    index = normalized.casefold().find(query.casefold())
    if index < 0:
        return normalized[:limit]
    start = max(0, index - 70)
    end = min(len(normalized), index + len(query) + 140)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end]}{suffix}"


def _looks_like_asset_reference(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(
        ("http://", "https://", "/app_data/", "/static/", "data:", "blob:")
    )


def _template_asset_url(value: Any) -> str | None:
    from utils.asset_directory_utils import normalize_slide_asset_url

    if isinstance(value, str):
        return normalize_slide_asset_url(value)
    if not isinstance(value, dict):
        return None

    fallback_url: str | None = None
    for key in (
        "data",
        "url",
        "image_url",
        "icon_url",
        "__image_url__",
        "__icon_url__",
    ):
        asset_url = value.get(key)
        if isinstance(asset_url, str) and asset_url.strip():
            normalized_url = normalize_slide_asset_url(asset_url)
            if _looks_like_asset_reference(normalized_url):
                return normalized_url
            if fallback_url is None:
                fallback_url = normalized_url
    return fallback_url


