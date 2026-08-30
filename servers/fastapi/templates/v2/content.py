"""Helpers for applying generated content to Template V2 element structures."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from .schema import get_repeated_top_level_group_schema_name


def hydrate_repeated_top_level_groups(
    elements: list[Any],
    content: Any,
    *,
    apply_item: Callable[[dict[str, Any], Any], dict[str, Any]],
) -> list[Any] | None:
    """Map one generated array item to each complete positioned group.

    Repeated top-level groups are one schema array even though each source group
    can have different positions and decorative connector geometry. Hydrating
    the array at the child level would discard the first item and duplicate the
    content child inside every positioned group.
    """
    if not isinstance(content, dict):
        return None

    field_name = get_repeated_top_level_group_schema_name(elements)
    if field_name is None:
        return None

    values = content.get(field_name)
    if not isinstance(values, list) or not elements:
        return None

    hydrated: list[Any] = []
    for index, value in enumerate(values):
        source = copy.deepcopy(elements[min(index, len(elements) - 1)])
        if not isinstance(source, dict):
            return None
        hydrated.append(apply_item(source, value))
    return hydrated
