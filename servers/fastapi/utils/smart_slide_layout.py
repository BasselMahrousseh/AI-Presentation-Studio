from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional


SLIDE_WIDTH = 1280.0
SLIDE_HEIGHT = 720.0
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_MEDIA_TAGS = {"canvas", "img", "svg", "table", "video"}
_NEGATIVE_LAYOUT_CLASS = re.compile(
    r"^-(?:m[trblxy]?|translate-[xy])-(?:\[|\d)", re.IGNORECASE
)
_NEGATIVE_LAYOUT_STYLE = re.compile(
    r"(?:margin(?:-top|-right|-bottom|-left)?\s*:\s*-|"
    r"transform\s*:[^;]*translate(?:X|Y|3d)?\([^)]*-)",
    re.IGNORECASE,
)
_STYLE_VALUE = re.compile(
    r"(?:^|;)\s*(left|right|top|bottom|width|height|position|overflow)\s*:"
    r"\s*([^;]+)",
    re.IGNORECASE,
)
_ARBITRARY_PX_CLASS = re.compile(
    r"^(left|right|top|bottom|w|h)-\[(-?\d+(?:\.\d+)?)px\]$",
    re.IGNORECASE,
)
_SPACING_CLASS = re.compile(
    r"^(left|right|top|bottom|w|h)-(\d+(?:\.5)?)$", re.IGNORECASE
)


class _LayoutNode:
    def __init__(
        self,
        tag: str,
        attrs: list[tuple[str, Optional[str]]],
        parent: Optional["_LayoutNode"],
    ) -> None:
        self.tag = tag.casefold()
        self.attrs = {name.casefold(): value or "" for name, value in attrs}
        self.parent = parent
        self.children: list[_LayoutNode] = []
        self.text: list[str] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    @property
    def styles(self) -> dict[str, str]:
        return {
            match.group(1).casefold(): match.group(2).strip()
            for match in _STYLE_VALUE.finditer(self.attrs.get("style", ""))
        }


class _LayoutParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[_LayoutNode] = []
        self.stack: list[_LayoutNode] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        parent = self.stack[-1] if self.stack else None
        node = _LayoutNode(tag, attrs, parent)
        if parent is None:
            self.roots.append(node)
        else:
            parent.children.append(node)
        if tag.casefold() not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag.casefold():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == normalized:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1].tag not in {"script", "style"}:
            self.stack[-1].text.append(data)


def _walk(node: _LayoutNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def _visible_text(node: _LayoutNode) -> str:
    parts = list(node.text)
    for child in node.children:
        if child.tag not in {"script", "style"}:
            parts.append(_visible_text(child))
    return " ".join(" ".join(parts).split())


def _contains_media(node: _LayoutNode) -> bool:
    return node.tag in _MEDIA_TAGS or any(_contains_media(child) for child in node.children)


def _is_decorative(node: _LayoutNode) -> bool:
    current: Optional[_LayoutNode] = node
    while current is not None:
        if current.attrs.get("aria-hidden", "").casefold() == "true":
            return True
        if current.attrs.get("data-decorative", "").casefold() == "true":
            return True
        current = current.parent
    return False


def _is_flex_column(node: _LayoutNode) -> bool:
    classes = node.classes
    return "flex" in classes and "flex-col" in classes


_NUMBERED_GRID_COLS_CLASS = re.compile(r"^grid-cols-(\d+)$")
# Below this, Tailwind's numbered grid-cols-N utility still leaves each track
# wide enough (at the slide's 1280px canvas) that text rarely wraps enough to
# overflow a shrink-to-fit row; arbitrary templates like grid-cols-[1fr_120px_1fr]
# are typically wide two-panel layouts, not narrow multi-card grids, and are
# deliberately excluded — narrowing this to the pattern that actually broke in
# practice keeps the false-positive rate low.
_NARROW_GRID_COLUMN_THRESHOLD = 3


def _numbered_grid_column_count(node: _LayoutNode) -> Optional[int]:
    if "grid" not in node.classes:
        return None
    for token in node.classes:
        match = _NUMBERED_GRID_COLS_CLASS.fullmatch(token)
        if match:
            return int(match.group(1))
    return None


_ARBITRARY_GRID_COLS_CLASS = re.compile(r"^grid-cols-\[(.+)\]$")


def _arbitrary_grid_column_count(node: _LayoutNode) -> Optional[int]:
    """Column count for an arbitrary grid template like
    `grid-cols-[0.88fr_1.12fr]` (Tailwind escapes literal spaces inside
    bracket values as underscores). Deliberately separate from the numbered
    check above — a class token can never match both patterns, so there is
    no overlap between the two."""
    if "grid" not in node.classes:
        return None
    for token in node.classes:
        match = _ARBITRARY_GRID_COLS_CLASS.fullmatch(token)
        if match:
            tracks = [part for part in re.split(r"[_\s]+", match.group(1)) if part]
            if tracks:
                return len(tracks)
    return None


def _is_shrink_to_fit_row(node: _LayoutNode) -> bool:
    classes = node.classes
    return "flex-1" in classes and "min-h-0" in classes


def _lacks_min_height_guard(node: _LayoutNode) -> bool:
    return "min-h-0" not in node.classes


def _find_shrink_to_fit_overflow_risks(root: _LayoutNode) -> list[str]:
    """Flag a fixed-height flex column whose shrink-marked, narrow-column grid
    cannot actually shrink, because its own card children have no `min-h-0`.
    Those cards keep their natural content height, silently overflow past the
    grid, and collide with whatever else is laid out in that column. Scoped to
    numbered grid-cols-N (N>=3) grids specifically: narrower tracks wrap text
    into more lines, which is what actually produces this overflow in
    practice — wide two-panel `grid-cols-[...]` layouts rarely do."""
    issues: list[str] = []
    for column in _walk(root):
        if _is_decorative(column) or not _is_flex_column(column):
            continue
        if _dimension_value(column, "height") is None:
            continue

        children = column.children
        for index, child in enumerate(children):
            if _is_decorative(child) or not _is_shrink_to_fit_row(child):
                continue
            column_count = _numbered_grid_column_count(child)
            if column_count is None or column_count < _NARROW_GRID_COLUMN_THRESHOLD:
                continue
            cards = [card for card in child.children if not _is_decorative(card)]
            if len(cards) < 2 or not any(
                _lacks_min_height_guard(card) for card in cards
            ):
                continue
            later_siblings = children[index + 1 :]
            if any(
                _is_meaningful(sibling) and not _is_decorative(sibling)
                for sibling in later_siblings
            ):
                issues.append(
                    f"A shrink-to-fit {column_count}-column grid (`flex-1 "
                    "min-h-0` with `grid-cols-"
                    f"{column_count}`) sits inside a fixed-height column and is "
                    "followed by more content, but its own card children are "
                    "missing `min-h-0` so they cannot actually shrink — narrow "
                    "columns like this wrap text into extra lines, and the "
                    "cards will overflow past the grid and collide with "
                    "whatever comes after it. Either give the fixed-height "
                    "column enough room for the cards' real content height, or "
                    "drop the fixed height so the column sizes to its content "
                    "instead of shrinking cards that cannot shrink."
                )
                break
    return issues


def _find_shrink_marked_grid_overflow_risks(root: _LayoutNode) -> list[str]:
    """Flag a `min-h-0`-marked grid row sitting inside an effectively
    fixed-height flex column, whose card children can't actually shrink
    (missing their own `min-h-0`) and are followed by more content.
    Generalizes the shrink-to-fit check above two ways real generation has
    produced: (1) the outer column's fixed height can come from
    `position: absolute` with both `top-*` and `bottom-*` set, not just an
    explicit `h-*` class; (2) the row can use an arbitrary two-panel
    template like `grid-cols-[0.88fr_1.12fr]`, not just a numbered
    `grid-cols-N`. Flex children shrink by default (`flex-shrink: 1`) —
    `min-h-0` alone, without `flex-1`, is enough to remove the min-content
    floor that would otherwise keep them from collapsing below their real
    content height, so `flex-1` is not required here the way the check
    above requires it."""
    issues: list[str] = []
    for column in _walk(root):
        if _is_decorative(column) or not _is_flex_column(column):
            continue
        if not _has_effective_fixed_height(column):
            continue

        children = column.children
        for index, child in enumerate(children):
            if _is_decorative(child) or "min-h-0" not in child.classes:
                continue
            column_count = _arbitrary_grid_column_count(child)
            if column_count is None or column_count < _MIN_CARD_ROW_COLUMNS:
                continue
            cards = [card for card in child.children if not _is_decorative(card)]
            if len(cards) < 2 or not any(
                _lacks_min_height_guard(card) and _is_meaningful(card)
                for card in cards
            ):
                continue
            later_siblings = children[index + 1 :]
            if any(
                _is_meaningful(sibling) and not _is_decorative(sibling)
                for sibling in later_siblings
            ):
                issues.append(
                    f"A `min-h-0`-marked {column_count}-column row "
                    "(`grid-cols-[...]`) sits inside a fixed-height column "
                    "(fixed via an explicit height or `position: absolute` "
                    "with both `top`/`bottom` set) and is followed by more "
                    "content, but at least one of its card children has no "
                    "`min-h-0` of its own. Flex children shrink by default, "
                    "so when the row is compressed to fit, that card's real "
                    "content does not shrink with it and silently overflows "
                    "past the row, colliding with whatever comes after. "
                    "Either give the fixed-height column enough room for "
                    "every card's real content, or drop `min-h-0` from this "
                    "row (and the outer column's fixed height, if needed) so "
                    "nothing is forced to shrink below its content."
                )
                break
    return issues


_MIN_CARD_ROW_COLUMNS = 2
_CARD_HEIGHT_CHARS_PER_PIXEL = 0.75
_CARD_HEIGHT_OVERHEAD_CHARS = 5.0
_CARD_ROW_GAP_PX = 16.0
_CARD_ROW_SAFE_WIDTH_PX = 1216.0
# Calibration reference: a real ~292px-wide card (one cell of a 4-column row
# at the 1216px safe content width) with ~240 combined characters of heading
# + body text visibly overflowed past its own border when given a 220px
# fixed height, but fit — with a little margin — at 380px. The formula below
# is fit to those two measured points, then scaled by estimated column width
# for other column counts. It cannot know real text wrapping or font
# metrics; it exists only to catch clearly excessive cases, not to validate
# borderline ones.
_CARD_WIDTH_CALIBRATION_PX = 292.0


def _estimated_column_width(column_count: int) -> float:
    return max(
        (_CARD_ROW_SAFE_WIDTH_PX - (column_count - 1) * _CARD_ROW_GAP_PX)
        / column_count,
        100.0,
    )


def _estimated_card_text_capacity(height_px: float, column_count: int) -> float:
    width_scale = _estimated_column_width(column_count) / _CARD_WIDTH_CALIBRATION_PX
    return max(
        (_CARD_HEIGHT_CHARS_PER_PIXEL * height_px - _CARD_HEIGHT_OVERHEAD_CHARS)
        * width_scale,
        0.0,
    )


def _find_fixed_height_card_text_overflow_risks(root: _LayoutNode) -> list[str]:
    """Flag a card with an explicit fixed height, inside a multi-column card
    row, whose own combined text is clearly more than that height can hold.
    Unlike the shrink-to-fit check above, this needs no `position: absolute`
    geometry and no `flex-1 min-h-0` wrapper — just a plain row of cards
    where one card's own text doesn't fit its own declared height. That
    overflow never crosses the canvas edge and the card is never
    `position: absolute`, so nothing else in this module can see it."""
    issues: list[str] = []
    for row in _walk(root):
        if _is_decorative(row):
            continue
        column_count = _numbered_grid_column_count(row)
        if column_count is None or column_count < _MIN_CARD_ROW_COLUMNS:
            continue
        for card in row.children:
            if _is_decorative(card):
                continue
            height = _dimension_value(card, "height")
            if height is None:
                continue
            text_length = len(_visible_text(card))
            if text_length == 0:
                continue
            capacity = _estimated_card_text_capacity(height, column_count)
            if text_length > capacity:
                issues.append(
                    f"A card with a fixed height of {height:.0f}px in a "
                    f"{column_count}-column row holds about {text_length} "
                    "characters of combined text — clearly more than that "
                    "height can fit, so it will overflow past its own "
                    "border. Shorten the card's text, or drop the fixed "
                    "height so it sizes to its content (`h-auto`) instead."
                )
    return issues


_MIN_STACKED_LIST_ITEMS = 4
_MIN_ITEM_TEXT_CHARACTERS = 20


def _has_fixed_or_matched_height(node: _LayoutNode) -> bool:
    """True for a container whose height is imposed by its layout context —
    either an explicit pixel height, or `h-full`/`self-stretch`, which
    stretches it to match a sibling (e.g. a full-height side rail next to a
    card grid). Content that stacks past this externally-imposed height has
    nowhere to go but past the bottom edge."""
    if _dimension_value(node, "height") is not None:
        return True
    return bool({"h-full", "self-stretch"} & node.classes)


def _has_effective_fixed_height(node: _LayoutNode) -> bool:
    """True for everything `_has_fixed_or_matched_height` catches, plus a
    container whose height is implied by `position: absolute` with both
    `top-*` and `bottom-*` set — a real pattern this generator produces
    (e.g. `absolute top-[72px] bottom-[96px]`) that never sets an explicit
    `h-*` class at all, so `_has_fixed_or_matched_height` alone misses it."""
    if _has_fixed_or_matched_height(node):
        return True
    return (
        _is_positioned(node)
        and _edge_value(node, "top") is not None
        and _edge_value(node, "bottom") is not None
    )


def _is_item_block(node: _LayoutNode) -> bool:
    return len(_visible_text(node)) >= _MIN_ITEM_TEXT_CHARACTERS


def _stacked_items(container: _LayoutNode) -> list[_LayoutNode]:
    """Direct children that look like list items. A panel commonly wraps its
    list in its own container alongside sibling heading/label elements (a
    `panel > label + heading + list-wrapper > items` shape) — so also look one
    level into any flex-column child and take whichever reading (direct
    children, or the richest nested wrapper) finds more items."""
    candidates = [
        child for child in container.children if not _is_decorative(child)
    ]
    direct_items = [child for child in candidates if _is_item_block(child)]
    nested_items: list[_LayoutNode] = []
    for child in candidates:
        if not _is_flex_column(child):
            continue
        inner = [
            grandchild
            for grandchild in child.children
            if not _is_decorative(grandchild) and _is_item_block(grandchild)
        ]
        if len(inner) > len(nested_items):
            nested_items = inner
    return nested_items if len(nested_items) >= len(direct_items) else direct_items


def _find_stacked_list_overflow_risks(root: _LayoutNode) -> list[str]:
    """Flag a height-matched panel (e.g. a full-height dark side rail) that
    stacks four or more text-heavy items in normal flow. Unlike a
    shrink-to-fit grid row colliding with a sibling below, a plain vertical
    stack has no sibling to collide with — it just grows past its own
    imposed height and gets clipped by the canvas's own `overflow-hidden`,
    which is why the checks above never catch it."""
    issues: list[str] = []
    for container in _walk(root):
        if _is_decorative(container) or not _is_flex_column(container):
            continue
        if not _has_fixed_or_matched_height(container):
            continue
        items = _stacked_items(container)
        if len(items) < _MIN_STACKED_LIST_ITEMS:
            continue
        issues.append(
            f"A height-matched panel (`h-full` or a fixed height) stacks "
            f"{len(items)} text-heavy items in normal flow with nothing to "
            "shrink them. A vertical stack like this has no sibling to "
            "collide with, so it overflows silently — it grows past its own "
            "height and gets clipped by the canvas's `overflow-hidden`. "
            "Reduce the item count, shorten each item to roughly one line, "
            "or drop the fixed/`h-full` height so the panel sizes to its "
            "real content instead."
        )
    return issues


def _is_meaningful(node: _LayoutNode) -> bool:
    return bool(_visible_text(node)) or _contains_media(node)


def _is_positioned(node: _LayoutNode) -> bool:
    return bool(
        {"absolute", "fixed"} & node.classes
        or node.styles.get("position", "").casefold() in {"absolute", "fixed"}
    )


def _dimension_value(node: _LayoutNode, property_name: str) -> Optional[float]:
    style_value = node.styles.get(property_name)
    if style_value:
        match = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", style_value)
        if match:
            return float(match.group(1))

    class_property = {"width": "w", "height": "h"}.get(
        property_name, property_name
    )
    for token in node.classes:
        arbitrary = _ARBITRARY_PX_CLASS.fullmatch(token)
        if arbitrary and arbitrary.group(1).casefold() == class_property:
            return float(arbitrary.group(2))
        spacing = _SPACING_CLASS.fullmatch(token)
        if spacing and spacing.group(1).casefold() == class_property:
            return float(spacing.group(2)) * 4.0
    return None


def _edge_value(node: _LayoutNode, edge: str) -> Optional[float]:
    if "inset-0" in node.classes or f"{edge}-0" in node.classes:
        return 0.0
    return _dimension_value(node, edge)


def _node_size(node: _LayoutNode) -> tuple[Optional[float], Optional[float]]:
    if node.parent is None:
        return SLIDE_WIDTH, SLIDE_HEIGHT
    width = _dimension_value(node, "width")
    height = _dimension_value(node, "height")
    if "w-full" in node.classes:
        width = _node_size(node.parent)[0]
    if "h-full" in node.classes:
        height = _node_size(node.parent)[1]
    return width, height


def _positioned_rect(
    node: _LayoutNode,
) -> Optional[tuple[float, float, float, float]]:
    parent_width, parent_height = _node_size(node.parent) if node.parent else (
        SLIDE_WIDTH,
        SLIDE_HEIGHT,
    )
    left = _edge_value(node, "left")
    right = _edge_value(node, "right")
    top = _edge_value(node, "top")
    bottom = _edge_value(node, "bottom")
    width, height = _node_size(node)

    if width is None and left is not None and right is not None and parent_width:
        width = parent_width - left - right
    if height is None and top is not None and bottom is not None and parent_height:
        height = parent_height - top - bottom
    if left is None and right is not None and width is not None and parent_width:
        left = parent_width - right - width
    if top is None and bottom is not None and height is not None and parent_height:
        top = parent_height - bottom - height
    if None in {left, top, width, height}:
        return None
    return float(left), float(top), float(width), float(height)


def _rectangles_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    overlap_width = min(first_x + first_width, second_x + second_width) - max(
        first_x, second_x
    )
    overlap_height = min(first_y + first_height, second_y + second_height) - max(
        first_y, second_y
    )
    return overlap_width > 4 and overlap_height > 4


def inspect_smart_slide_layout(html: str) -> list[str]:
    """Return deterministic risks that commonly produce clipped/overlapping slides."""
    parser = _LayoutParser()
    parser.feed(html)
    if not parser.roots:
        return []
    root = parser.roots[0]
    issues: list[str] = []
    positioned_by_parent: dict[int, list[tuple[_LayoutNode, tuple[float, float, float, float]]]] = {}

    for node in _walk(root):
        if node is root or not _is_meaningful(node) or _is_decorative(node):
            continue

        if any(_NEGATIVE_LAYOUT_CLASS.match(token) for token in node.classes) or (
            _NEGATIVE_LAYOUT_STYLE.search(node.attrs.get("style", ""))
        ):
            issues.append(
                "Meaningful content uses a negative margin or translation that can overlap nearby content."
            )

        has_hidden_overflow = "overflow-hidden" in node.classes or (
            node.styles.get("overflow", "").casefold() == "hidden"
        )
        if has_hidden_overflow and _visible_text(node):
            issues.append(
                "A nested container hides text overflow instead of fitting all text visibly."
            )

        if not _is_positioned(node):
            continue
        rect = _positioned_rect(node)
        if rect is None:
            issues.append(
                "Absolutely positioned meaningful content is missing a complete pixel box; use flex/grid or provide left/top/width/height."
            )
            continue
        x, y, width, height = rect
        parent_width, parent_height = _node_size(node.parent) if node.parent else (
            SLIDE_WIDTH,
            SLIDE_HEIGHT,
        )
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            issues.append("Positioned meaningful content has invalid or off-canvas geometry.")
        elif parent_width is not None and x + width > parent_width + 1:
            issues.append("Positioned meaningful content crosses the right slide/container boundary.")
        elif parent_height is not None and y + height > parent_height + 1:
            issues.append("Positioned meaningful content crosses the bottom slide/container boundary.")

        positioned_by_parent.setdefault(id(node.parent), []).append((node, rect))

    for siblings in positioned_by_parent.values():
        for first_index, (_, first_rect) in enumerate(siblings):
            for _, second_rect in siblings[first_index + 1 :]:
                if _rectangles_overlap(first_rect, second_rect):
                    issues.append(
                        "Absolutely positioned sibling content boxes overlap; reflow them with flex/grid and explicit gaps."
                    )

    issues.extend(_find_shrink_to_fit_overflow_risks(root))
    issues.extend(_find_shrink_marked_grid_overflow_risks(root))
    issues.extend(_find_fixed_height_card_text_overflow_risks(root))
    issues.extend(_find_stacked_list_overflow_risks(root))

    return list(dict.fromkeys(issues))
