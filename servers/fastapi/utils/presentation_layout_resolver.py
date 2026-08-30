"""Shared logic for turning a `PresentationModel.layout` payload into a `PresentationLayoutModel`.

A presentation's `layout` column has taken on more than one shape over time:
a legacy single-layout dict (`PresentationLayoutModel(**layout)` works directly),
a template-picker payload (`{"layouts": [...], "template_id": ...}`), or `None`
for presentations whose layout instead lives in the `template_v2` table. Any
code that needs the resolved layout model for an existing presentation should
call `resolve_presentation_layout_model` rather than `presentation.get_layout()`
directly, which only handles the legacy shape.
"""

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.sql.presentation import PresentationModel
from models.sql.template_v2 import TemplateV2
from templates.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from templates.v2.schema import get_template_schema
from utils.icon_weights import extract_icon_type_from_settings

CUSTOM_TEMPLATE_PREFIX = "custom-"


def is_template_layout_payload(layout_payload: Any) -> bool:
    return isinstance(layout_payload, dict) and isinstance(
        layout_payload.get("layouts"), list
    )


def extract_template_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith(CUSTOM_TEMPLATE_PREFIX):
        candidate = candidate[len(CUSTOM_TEMPLATE_PREFIX) :].strip()
    return candidate or None


def build_template_layout_model(
    layout_payload: dict[str, Any],
    *,
    layout_name: str,
) -> PresentationLayoutModel:
    template_schema = get_template_schema(layout_payload)
    source_layouts = layout_payload.get("layouts")
    if not isinstance(source_layouts, list):
        source_layouts = []

    slides: list[SlideLayoutModel] = []
    for index, schema_layout in enumerate(template_schema["layouts"]):
        if not isinstance(schema_layout, dict):
            continue

        source_layout = (
            source_layouts[index]
            if index < len(source_layouts) and isinstance(source_layouts[index], dict)
            else {}
        )
        layout_id = (
            schema_layout.get("layout_id")
            or source_layout.get("id")
            or f"layout_{index + 1}"
        )
        layout_schema = schema_layout.get("schema")
        if not isinstance(layout_schema, dict):
            layout_schema = {
                "title": str(layout_id),
                "description": source_layout.get("description"),
            }

        slides.append(
            SlideLayoutModel(
                id=str(layout_id),
                name=source_layout.get("name") or layout_schema.get("title"),
                description=source_layout.get("description")
                or layout_schema.get("description"),
                json_schema=layout_schema,
            )
        )

    return PresentationLayoutModel(
        name=layout_name,
        ordered=False,
        icon_type=extract_icon_type_from_settings(layout_payload),
        slides=slides,
    )


async def resolve_template_layout_model(
    presentation: PresentationModel,
    sql_session: AsyncSession,
) -> PresentationLayoutModel | None:
    candidate_ids: list[str] = []
    seen_ids: set[str] = set()

    if isinstance(presentation.layout, dict):
        for key in ("name", "template_id"):
            template_id = extract_template_id(presentation.layout.get(key))
            if template_id and template_id not in seen_ids:
                candidate_ids.append(template_id)
                seen_ids.add(template_id)

    for template_id in candidate_ids:
        template = await sql_session.get(TemplateV2, template_id)
        if not template or not isinstance(template.layouts, dict):
            continue
        layout_payload = copy.deepcopy(template.layouts)
        icon_type = extract_icon_type_from_settings(template.assets)
        layout_payload["icon_type"] = icon_type
        layout_payload["icon_weight"] = icon_type
        return build_template_layout_model(
            layout_payload,
            layout_name=f"{CUSTOM_TEMPLATE_PREFIX}{template.id}",
        )

    return None


async def resolve_presentation_layout_model(
    presentation: PresentationModel,
    sql_session: AsyncSession,
) -> PresentationLayoutModel | None:
    if not isinstance(presentation.layout, dict):
        return await resolve_template_layout_model(presentation, sql_session)

    if is_template_layout_payload(presentation.layout):
        return build_template_layout_model(
            presentation.layout,
            layout_name=str(presentation.layout.get("name") or "template"),
        )

    try:
        return presentation.get_layout()
    except Exception:
        return await resolve_template_layout_model(presentation, sql_session)
