"""Reference-only transformations shared by explicit file and database migrations.

No network, environment loading, ORM initialization, or arbitrary prose rewriting.
"""

import html
import json
import re
from urllib.parse import urlsplit
import uuid

from api.v1.auth.assets import normalized_app_data_parts, SHARED_APP_DATA_ROOTS, PRIVATE_APP_DATA_ROOTS


MEDIA_KEYS = {
    "src", "href", "url", "poster", "image", "image_url", "image_path",
    "imagePath", "file_path", "backgroundImage", "background_image", "srcset",
}
HTML_KEYS = {"html", "html_content"}
_HTML_SEGMENT = re.compile(r"<!--.*?-->|<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_ATTRIBUTE = re.compile(r'''(\b(?:src|href|xlink:href|poster|srcset|style)\s*=\s*)(["'])(.*?)\2''', re.IGNORECASE | re.DOTALL)
_CSS_URL = re.compile(r'''url\(\s*(["']?)(.*?)\1\s*\)''', re.IGNORECASE)
_STYLE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.IGNORECASE | re.DOTALL)
_SCRIPT = re.compile(r"(<script\b[^>]*>)(.*?)(</script\s*>)", re.IGNORECASE | re.DOTALL)


def owner_string(value) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(bytes=bytes(value))) if isinstance(value, (bytes, bytearray)) else str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        return None


def _css(value, transform):
    return _CSS_URL.sub(lambda match: f'url("{transform(match.group(2))}")', value)


def _srcset(value, transform):
    if value.lstrip().startswith("data:"):
        return value
    return ", ".join(
        " ".join((transform(bits[0]), *bits[1:]))
        for item in value.split(",") if (bits := item.strip().split())
    )


def transform_html_references(value: str, transform) -> str:
    def tag(raw):
        def attribute(attribute_match):
            name = attribute_match.group(1).split("=", 1)[0].strip().lower()
            original = html.unescape(attribute_match.group(3))
            if name == "style":
                changed = _css(original, transform)
            elif name == "srcset":
                changed = _srcset(original, transform)
            else:
                changed = transform(original)
            if changed == original:
                return attribute_match.group(0)
            return attribute_match.group(1) + '"' + html.escape(changed, quote=True) + '"'
        return _ATTRIBUTE.sub(attribute, raw)
    def segment(match):
        raw = match.group(0)
        if raw.startswith("<!--"):
            return raw
        script = _SCRIPT.fullmatch(raw)
        if script:
            return tag(script.group(1)) + script.group(2) + script.group(3)
        style = _STYLE.fullmatch(raw)
        if style:
            return tag(style.group(1)) + _css(style.group(2), transform) + style.group(3)
        return tag(raw)
    return _HTML_SEGMENT.sub(segment, value)


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def transform_media_json(value, transform, *, decode=True):
    value = _json_value(value) if decode else value
    if isinstance(value, list):
        return [transform_media_json(item, transform, decode=False) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in HTML_KEYS and isinstance(item, str):
            result[key] = transform_html_references(item, transform)
        elif key in MEDIA_KEYS and isinstance(item, str):
            if key == "srcset":
                result[key] = _srcset(item, transform)
            elif key in {"backgroundImage", "background_image"} and "url(" in item:
                result[key] = _css(item, transform)
            else:
                result[key] = transform(item)
        else:
            result[key] = transform_media_json(item, transform, decode=False) if isinstance(item, (dict, list)) else item
    return result


def transform_record_references(table: str, row: dict, transform) -> dict:
    """Return changes only for columns proven to hold storage references.

    transform(value, owner_id, field, required_kind) returns the new reference;
    required_kind is uploads/images for authoritative paths, None for media.
    """
    owner = owner_string(row.get("owner_id"))
    changes = {}

    def change(field, value):
        if value != _json_value(row.get(field)):
            changes[field] = value

    if table == "GENAI_WORKSPACE_IMAGE_ASSET":
        change("path", transform(row.get("path"), owner, "path", "images"))
    if table == "GENAI_WORKSPACE_PRESENTATION":
        paths = _json_value(row.get("file_paths"))
        if paths is not None:
            if not isinstance(paths, list):
                raise ValueError("Presentation file_paths must be a JSON array")
            change("file_paths", [transform(path, owner, "file_paths", "uploads") for path in paths])
    json_fields = {
        "GENAI_WORKSPACE_SLIDE": ("content", "properties", "ui"),
        "GENAI_WORKSPACE_PRESENTATION": ("layout", "theme", "fonts", "source_quality_flags"),
    }.get(table, ())
    for field in json_fields:
        if row.get(field) is not None:
            original = _json_value(row[field])
            if field == "fonts" and isinstance(original, dict):
                # Runtime font maps are family -> URL, not generic content JSON.
                value = {key: transform(item, owner, field, None) if isinstance(item, str)
                    else transform_media_json(item, lambda item: transform(item, owner, field, None))
                    for key, item in original.items()}
            else:
                value = transform_media_json(original, lambda value: transform(value, owner, field, None))
            change(field, value)
    if table == "GENAI_WORKSPACE_SLIDE" and row.get("html_content"):
        value = transform_html_references(row["html_content"], lambda value: transform(value, owner, "html_content", None))
        if value != row["html_content"]:
            changes["html_content"] = value
    return changes


def assert_portable_database_references(rows_by_table: dict) -> None:
    """Reject machine-local/cross-owner durable references before Oracle row copy."""
    issues = []
    for table, rows in rows_by_table.items():
        for row in rows:
            def validate(value, owner, field, required_kind):
                if not isinstance(value, str) or not value:
                    if required_kind:
                        issues.append(f"{table}/{row.get('id')}/{field}: missing asset reference")
                    return value
                parts = normalized_app_data_parts(value) if value.startswith("/app_data/") and not any(c in value for c in "?#") else None
                if parts:
                    if parts[0] not in SHARED_APP_DATA_ROOTS | PRIVATE_APP_DATA_ROOTS:
                        issues.append(f"{table}/{row.get('id')}/{field}: unsupported asset kind")
                    elif required_kind and parts[0] != required_kind:
                        issues.append(f"{table}/{row.get('id')}/{field}: wrong asset kind")
                    elif parts[0] not in SHARED_APP_DATA_ROOTS and not (
                        owner and len(parts) >= 4 and parts[1:3] == ("users", owner)
                    ):
                        issues.append(f"{table}/{row.get('id')}/{field}: asset owner mismatch")
                    return value
                parsed = urlsplit(value)
                is_local = (
                    value.startswith(("/app_data/", "file:", "/", "\\"))
                    and not value.startswith(("/static/", "//"))
                ) or bool(re.match(r"^[A-Za-z]:[\\/]", value)) or parsed.path.startswith("/app_data/")
                if required_kind or is_local:
                    issues.append(f"{table}/{row.get('id')}/{field}: file migration required")
                return value
            transform_record_references(table, dict(row), validate)
    if issues:
        raise ValueError("Non-portable Studio asset references: " + "; ".join(issues))
