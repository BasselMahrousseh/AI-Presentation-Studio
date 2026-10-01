"""Bounded declarative chart data shared by Smart generation and rendering.

The UI reads the same canvas-id -> Chart.js configuration contract. This module
accepts data only; it never evaluates JavaScript or creates provider callbacks.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any


CHART_TYPES = frozenset({"bar", "line", "pie", "doughnut", "scatter", "bubble", "radar", "polarArea"})
_RESERVED_KEYS = frozenset({"__proto__", "constructor", "prototype"})
_CANVAS_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _invalid_constant(_value: str):
    raise ValueError("Chart numbers must be finite")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result or key in _RESERVED_KEYS:
            raise ValueError("Chart data contains a duplicate or reserved key")
        result[key] = value
    return result


def parse_smart_chart_data(source: str) -> dict[str, dict[str, Any]]:
    """Validate one data-presenton-charts script and return renderer-safe data."""
    if len(source) > 512_000:
        raise ValueError("Chart configuration is too large")
    try:
        value = json.loads(source, parse_constant=_invalid_constant, object_pairs_hook=_unique_object)
    except (RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Chart configuration must be valid JSON") from exc
    if not isinstance(value, dict) or not 1 <= len(value) <= 24:
        raise ValueError("Chart configuration must map between 1 and 24 canvas IDs")

    remaining = 20_000

    def bounded(item, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise ValueError("Chart data exceeds its complexity limit")
        if isinstance(item, str):
            if len(item) > 4096:
                raise ValueError("Chart text is too long")
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("Chart numbers must be finite")
        elif isinstance(item, list):
            if len(item) > 2000:
                raise ValueError("Chart array is too long")
            for entry in item:
                bounded(entry, depth + 1)
        elif isinstance(item, dict):
            for key, entry in item.items():
                bounded(key, depth + 1)
                bounded(entry, depth + 1)

    bounded(value)
    result = {}
    for canvas_id, config in value.items():
        if not _CANVAS_ID.fullmatch(canvas_id) or not isinstance(config, dict):
            raise ValueError("Invalid chart canvas identity or configuration")
        if not isinstance(config.get("type"), str) or config["type"] not in CHART_TYPES:
            raise ValueError("Unsupported chart type")
        data = config.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("datasets"), list):
            raise ValueError("Chart data requires datasets")
        datasets = data["datasets"]
        if not 1 <= len(datasets) <= 32 or any(
            not isinstance(dataset, dict) or not isinstance(dataset.get("data"), list)
            for dataset in datasets
        ):
            raise ValueError("Chart datasets must contain data arrays")
        if "labels" in data and not isinstance(data["labels"], list):
            raise ValueError("Chart labels must be an array")
        options = config.get("options", {})
        if not isinstance(options, dict):
            raise ValueError("Chart options must be an object")
        result[canvas_id] = {
            "type": config["type"], "data": data,
            "options": {**options, "responsive": False, "animation": False, "events": []},
        }
    return result


def chart_data_script(data: dict[str, dict[str, Any]]) -> str:
    content = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    return '<script type="application/json" data-presenton-charts>' + content + '</script>'
