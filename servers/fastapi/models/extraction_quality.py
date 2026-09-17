from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel


class VisualExtractability(str, Enum):
    NATIVE_DATA = "native_data"
    PARTIAL = "partial"
    IMAGE_ONLY = "image_only"


class VisualQualityFlag(BaseModel):
    """One chart/table/image whose underlying data could not be fully recovered.

    Only PARTIAL and IMAGE_ONLY visuals are ever turned into a flag - a
    successfully (fully) extracted visual has nothing to review, so it never
    appears here at all.
    """

    source_file: str
    location: str
    visual_label: Optional[str] = None
    visual_kind: Literal["chart", "table", "image"] = "chart"
    status: VisualExtractability
    detail: str
    recommendation: str


class QualityFlagGroup(BaseModel):
    """One (source_file, status) group of flags, as shown in the review UI.

    Grouping happens here, at the API/serialization layer - the underlying
    VisualQualityFlag list stays flat and ungrouped.
    """

    group_key: str
    source_file: str
    status: VisualExtractability
    summary: str
    items: List[VisualQualityFlag]
    acknowledged: bool = False


class AcknowledgeQualityFlagGroupsRequest(BaseModel):
    group_keys: List[str]


def _group_key(source_file: str, status: VisualExtractability) -> str:
    return f"{source_file}::{status.value}"


def _summarize_group(status: VisualExtractability, count: int) -> str:
    noun = "visual" if count == 1 else "visuals"
    if status is VisualExtractability.IMAGE_ONLY:
        verb = "has" if count == 1 else "have"
        return f"{count} {noun} {verb} no extractable data (screenshot-only)"
    # PARTIAL
    verb = "was" if count == 1 else "were"
    return (
        f"{count} {noun} {verb} only partially recovered — some values may be "
        "missing or the chart type couldn't be matched"
    )


def group_quality_flags(
    flags: List[VisualQualityFlag], acknowledged_keys: Optional[List[str]] = None
) -> List[QualityFlagGroup]:
    acknowledged = set(acknowledged_keys or [])
    buckets: dict[tuple[str, VisualExtractability], list[VisualQualityFlag]] = {}
    order: list[tuple[str, VisualExtractability]] = []
    for flag in flags:
        key = (flag.source_file, flag.status)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(flag)

    # Most-actionable first: image_only groups before partial ones, larger
    # groups before smaller ones within the same status.
    def sort_key(key: tuple[str, VisualExtractability]):
        source_file, status = key
        status_rank = 0 if status is VisualExtractability.IMAGE_ONLY else 1
        return (status_rank, -len(buckets[key]), source_file)

    groups: List[QualityFlagGroup] = []
    for source_file, status in sorted(order, key=sort_key):
        items = buckets[(source_file, status)]
        key_str = _group_key(source_file, status)
        groups.append(
            QualityFlagGroup(
                group_key=key_str,
                source_file=source_file,
                status=status,
                summary=_summarize_group(status, len(items)),
                items=items,
                acknowledged=key_str in acknowledged,
            )
        )
    return groups
