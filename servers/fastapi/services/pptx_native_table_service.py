import logging
import uuid
from typing import Any, Optional

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu

from services import table_capture_store
from services.pptx_native_export_shared import (
    _DESIGN_HEIGHT_PX,
    _DESIGN_WIDTH_PX,
    _IOU_AMBIGUITY_MARGIN,
    _IOU_MIN,
    _alpha_from_css_color,
    _best_overlap_match,
    _clamp_rect_to_slide,
    _expected_slide_count,
    _group_by_slide_order,
    _hex_from_css_color,
    _pt_from_css_px,
    _rect_to_emu,
    _shape_rect,
    _slide_dimensions_emu,
)

LOGGER = logging.getLogger(__name__)

# A 500-cell table isn't legible on a 1280x720 slide regardless of how it's
# styled - real stress-test tables top out at 30 cells. This is a sanity cap,
# not a measured limit the way the chart pipeline's caps are (see
# _MAX_TABLES_PER_REQUEST in the capture endpoint for the same caveat).
_MAX_TABLE_CELLS = 500

_TEXT_ALIGN_TO_PP_ALIGN: dict[str, PP_ALIGN] = {
    "left": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,
    "justify": PP_ALIGN.JUSTIFY,
}

# A captured fontWeight can be a browser-computed numeric CSS value ("700"),
# a real number, or the keyword "bold"/"normal" - never trust it blindly, and
# never raise on a garbage value from an untrusted capture payload.
_BOLD_FONT_WEIGHT_THRESHOLD = 600


def _font_weight_is_bold(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value >= _BOLD_FONT_WEIGHT_THRESHOLD
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "bold":
            return True
        if text == "normal":
            return False
        try:
            return float(text) >= _BOLD_FONT_WEIGHT_THRESHOLD
        except ValueError:
            return False
    return False


def _build_table_grid(captured_table: dict) -> Optional[dict]:
    """Validates a captured table's grid shape and returns a normalized copy
    (ints coerced, cells sorted by anchor) for the rest of this module to
    consume, or None if the payload can't safely become a real table -
    same "None -> caller leaves the picture flattened" contract as the chart
    pipeline's _build_chart_data."""
    row_count = captured_table.get("rowCount")
    col_count = captured_table.get("colCount")
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count <= 0:
        return None
    if not isinstance(col_count, int) or isinstance(col_count, bool) or col_count <= 0:
        return None
    if row_count * col_count > _MAX_TABLE_CELLS:
        return None

    raw_cells = captured_table.get("cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        return None

    normalized_cells: list[dict] = []
    seen_anchors: set[tuple[int, int]] = set()
    for cell in raw_cells:
        if not isinstance(cell, dict):
            return None
        row_index = cell.get("rowIndex")
        col_index = cell.get("colIndex")
        row_span = cell.get("rowSpan", 1)
        col_span = cell.get("colSpan", 1)
        for value in (row_index, col_index, row_span, col_span):
            if not isinstance(value, int) or isinstance(value, bool):
                return None
        if row_span < 1 or col_span < 1:
            return None
        if row_index < 0 or col_index < 0:
            return None
        if row_index + row_span > row_count or col_index + col_span > col_count:
            return None
        anchor = (row_index, col_index)
        if anchor in seen_anchors:
            return None
        seen_anchors.add(anchor)
        normalized_cells.append(
            {
                **cell,
                "rowIndex": row_index,
                "colIndex": col_index,
                "rowSpan": row_span,
                "colSpan": col_span,
            }
        )

    return {
        "rowCount": row_count,
        "colCount": col_count,
        "cells": normalized_cells,
        "boundingBox": captured_table.get("boundingBox"),
        "columnWidthsPx": captured_table.get("columnWidthsPx"),
        "rowHeightsPx": captured_table.get("rowHeightsPx"),
    }


def _looks_like_header_row(cells: list[dict], col_count: int) -> bool:
    row_zero = [cell for cell in cells if cell["rowIndex"] == 0]
    if not row_zero:
        return False
    if any(cell.get("isHeaderCell") for cell in row_zero):
        return True
    bold_count = sum(1 for cell in row_zero if _font_weight_is_bold(cell.get("fontWeight")))
    # A plain, unbold first row with no <thead> correctly gets no header
    # styling here - a safe failure mode (looks like an ordinary data row)
    # rather than mis-styling something.
    return bold_count > col_count / 2


def _apply_table_content(table, captured_table: dict) -> None:
    """Must-succeed: sets each captured cell's text and alignment. Any
    failure here means the grid we already validated doesn't actually match
    the real python-pptx table - a real bug, not user input - so it's left
    unguarded and propagates to the caller's rollback logic."""
    for cell in captured_table["cells"]:
        table_cell = table.cell(cell["rowIndex"], cell["colIndex"])
        text = cell.get("text")
        if isinstance(text, str) and text:
            table_cell.text_frame.text = text
        # Empty cells: text stays "" -> add_run() is skipped (python-pptx's
        # default cell already has one empty paragraph), but alignment/fill
        # still apply below/in styling - covers a colored-but-textless
        # status cell.
        align = _TEXT_ALIGN_TO_PP_ALIGN.get(cell.get("textAlign"))
        if align is not None:
            for paragraph in table_cell.text_frame.paragraphs:
                paragraph.alignment = align


def _apply_table_merges(table, captured_table: dict) -> None:
    """Separate pass, run after content is set: python-pptx's .merge()
    operates on cell identity, and the anchor cell (which content was
    already written to) keeps its content after merging - the consumed
    positions never had anything written to begin with. Each merge is
    isolated in its own try/except so one bad span doesn't sink the whole
    table."""
    for cell in captured_table["cells"]:
        row_span, col_span = cell["rowSpan"], cell["colSpan"]
        if row_span <= 1 and col_span <= 1:
            continue
        row_index, col_index = cell["rowIndex"], cell["colIndex"]
        try:
            table.cell(row_index, col_index).merge(
                table.cell(row_index + row_span - 1, col_index + col_span - 1)
            )
        except ValueError:
            LOGGER.warning(
                "pptx_native_table_service: skipping one invalid merge "
                "(row=%s col=%s rowSpan=%s colSpan=%s)",
                row_index,
                col_index,
                row_span,
                col_span,
            )


def _distribute_to_total(fractions: list[float], total: int) -> list[int]:
    """Largest-remainder rounding: converts proportional fractions into
    integer EMU values that sum exactly to `total`, so column widths/row
    heights never drift from the table's actual frame size through
    accumulated rounding error."""
    if not fractions or total <= 0:
        return [0 for _ in fractions]
    raw = [f * total for f in fractions]
    floors = [int(x) for x in raw]
    remainder = total - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in range(max(remainder, 0)):
        floors[order[i % len(floors)]] += 1
    return floors


# A row-separator line thicker than this is almost certainly a misread
# capture (e.g. a captured value in the wrong units), not a real design
# choice - real generated tables use 1-2px hairlines. Bounds a garbage
# value away from producing a comically thick or inverted-looking border,
# same defensive-bounds style as _pt_from_css_px's own min/max guard.
_MIN_BORDER_WIDTH_PX = 0.5
_MAX_BORDER_WIDTH_PX = 20.0


def _apply_cell_bottom_border(
    table_cell, hex_color: str, alpha: Optional[float], width_emu: int
) -> None:
    """
    python-pptx exposes zero API for table cell borders - confirmed by
    inspecting both `pptx.table._Cell` and `pptx.table.Table`'s full public
    attribute lists directly (`fill`/`margin_*`/`text`/... on the cell,
    nothing about lines at all) and `pptx.oxml.table.CT_TableCellProperties`'s
    own schema declaration (only `eg_fillProperties` and margin/anchor
    attributes - no `lnL`/`lnR`/`lnT`/`lnB` modeled anywhere in this
    library). This inserts `<a:lnB>` directly into the cell's `<a:tcPr>`, the
    same "hand-author what python-pptx doesn't expose" pattern already used
    by the chart service's `_apply_fill_alpha`/`_make_chart_background_transparent`.

    Per ECMA-376's `CT_TableCellProperties` sequence, `lnB` must precede any
    fill/headers element already present. Since python-pptx's own oxml class
    doesn't model `lnB` at all, its insertion-position logic for the fill
    group (added by `fill.solid()`) has no awareness of it either - so this
    doesn't rely on that machinery. This codebase only ever adds `lnB` here
    (never `lnL`/`lnR`/`lnT`), so inserting it as `tcPr`'s first child is
    always schema-correct regardless of whether a fill was already added
    before or after this call.
    """
    tcPr = table_cell._tc.get_or_add_tcPr()
    for existing in tcPr.findall(qn("a:lnB")):
        tcPr.remove(existing)

    lnB = etree.Element(qn("a:lnB"))
    lnB.set("w", str(int(width_emu)))
    solidFill = etree.SubElement(lnB, qn("a:solidFill"))
    srgbClr = etree.SubElement(solidFill, qn("a:srgbClr"))
    srgbClr.set("val", hex_color)
    if alpha is not None:
        alpha_el = etree.SubElement(srgbClr, qn("a:alpha"))
        alpha_el.set("val", str(int(round(alpha * 100000))))

    tcPr.insert(0, lnB)


def _apply_table_styling(
    table, captured_table: dict, emu_per_px_x: float = 1.0, emu_per_px_y: float = 1.0
) -> None:
    """Best-effort: cosmetic-only, wrapped by the caller's broad except so a
    failure here leaves a structurally-correct table with default styling -
    strictly better than a flattened picture."""
    col_count = captured_table["colCount"]
    row_count = captured_table["rowCount"]
    cells = captured_table["cells"]

    for cell in cells:
        table_cell = table.cell(cell["rowIndex"], cell["colIndex"])

        bg_hex = _hex_from_css_color(cell.get("backgroundColor"))
        if bg_hex:
            table_cell.fill.solid()
            table_cell.fill.fore_color.rgb = RGBColor.from_string(bg_hex)

        border_hex = _hex_from_css_color(cell.get("bottomBorderColor"))
        border_width_px = cell.get("bottomBorderWidthPx")
        if (
            border_hex
            and isinstance(border_width_px, (int, float))
            and not isinstance(border_width_px, bool)
            and _MIN_BORDER_WIDTH_PX <= border_width_px <= _MAX_BORDER_WIDTH_PX
        ):
            width_emu = int(round(border_width_px * emu_per_px_y))
            if width_emu > 0:
                border_alpha = _alpha_from_css_color(cell.get("bottomBorderColor"))
                _apply_cell_bottom_border(table_cell, border_hex, border_alpha, width_emu)

        font_color_hex = _hex_from_css_color(cell.get("textColor"))
        font_pt = _pt_from_css_px(cell.get("fontSize"))
        font_family = cell.get("fontFamily")
        is_bold = _font_weight_is_bold(cell.get("fontWeight"))

        for paragraph in table_cell.text_frame.paragraphs:
            for run in paragraph.runs:
                if font_color_hex:
                    run.font.color.rgb = RGBColor.from_string(font_color_hex)
                if font_pt is not None:
                    run.font.size = font_pt
                if isinstance(font_family, str) and font_family.strip():
                    run.font.name = font_family.strip()
                if is_bold:
                    run.font.bold = True

    table.first_row = _looks_like_header_row(cells, col_count)
    # Deliberately OFF, not the seemingly-safer "cosmetic default" this used
    # to be. A direct per-cell fill (set above) always wins over table-style
    # banding in OOXML, so real captured colors are never affected by this
    # flag either way - but when a body row genuinely has no explicit
    # background in the source (the common case: a plain white table with
    # just border-bottom lines between rows, confirmed against a real user
    # report and its actual generated HTML), leaving banding on fabricates
    # PowerPoint's own default alternating-row stripe pattern out of nothing,
    # visibly diverging from the original design rather than matching it.
    # Banding never helps (real colors override it) and can only hurt
    # (invents a pattern that was never there), so there's no case where
    # leaving it on is the better default.
    table.horz_banding = False

    column_widths_px = captured_table.get("columnWidthsPx")
    if (
        isinstance(column_widths_px, list)
        and len(column_widths_px) == col_count
        and all(isinstance(w, (int, float)) and w > 0 for w in column_widths_px)
    ):
        total_width = sum(table.columns[i].width for i in range(col_count))
        width_sum = sum(column_widths_px)
        fractions = [w / width_sum for w in column_widths_px]
        for index, width_emu in enumerate(_distribute_to_total(fractions, total_width)):
            table.columns[index].width = Emu(width_emu)
    # else: no usable per-column widths (e.g. every row had a colspan) ->
    # add_table()'s equal-width default stands, per the documented V1
    # limitation.

    row_heights_px = captured_table.get("rowHeightsPx")
    if (
        isinstance(row_heights_px, list)
        and len(row_heights_px) == row_count
        and all(isinstance(h, (int, float)) and h > 0 for h in row_heights_px)
    ):
        total_height = sum(table.rows[i].height for i in range(row_count))
        height_sum = sum(row_heights_px)
        fractions = [h / height_sum for h in row_heights_px]
        for index, height_emu in enumerate(_distribute_to_total(fractions, total_height)):
            table.rows[index].height = Emu(height_emu)


# The closed-source export converter does NOT always flatten a <table> into
# one single whole-table screenshot the way CLAUDE.md's own original
# assumption (and this pipeline's design) expected. Confirmed by inspecting
# a real converted file's full shape list: for a table with per-cell
# background colors/borders (a colored header row, banded rows, bordered
# cells - i.e. most real generated tables), the converter also emits a
# SEPARATE PICTURE (that cell's background/border, rasterized) plus a
# SEPARATE TEXT_BOX (that cell's real text, already a native shape) for
# EVERY cell, layered on top of/alongside one whole-table backdrop picture.
# _try_upgrade_one_table's IoU matching correctly finds and swaps out that
# one backdrop picture - but the per-cell fragments were never claimed by
# anything, so they were silently left behind, stacking their own (still
# correct, but now redundant) text and coloring on top of the brand-new
# native table. Real user report: every cell's text visually duplicated,
# stacked in two lines - one from the native table, one from the leftover
# fragment's own PICTURE/TEXT_BOX pair sitting at the exact same position.
# Confirmed present in 100% of tables converted this session (23-58 leftover
# fragments per table, scaling with cell count) once someone actually opened
# a real export and looked past the table shape's own (always-correct)
# python-pptx .text property - this codebase's own repeated lesson that a
# python-pptx-level check is not sufficient proof of a correct *file*.
_LEFTOVER_FRAGMENT_CONTAINMENT_MIN = 0.9
_LEFTOVER_FRAGMENT_SHAPE_TYPES = (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.TEXT_BOX)


def _containment_ratio(outer: Any, inner: Any) -> float:
    """What fraction of `inner`'s own area sits inside `outer`. 1.0 means
    `inner` is entirely contained; 0.0 means no overlap at all. Deliberately
    NOT the same metric as _iou (which penalizes outer being much bigger than
    inner) - a small per-cell fragment sitting inside a much larger table is
    exactly the case this needs to catch confidently."""
    ox0, oy0, ow, oh = outer
    ix0, iy0, iw, ih = inner
    if iw <= 0 or ih <= 0:
        return 0.0
    ox1, oy1 = ox0 + ow, oy0 + oh
    ix1, iy1 = ix0 + iw, iy0 + ih
    inter_w = max(0, min(ox1, ix1) - max(ox0, ix0))
    inter_h = max(0, min(oy1, iy1) - max(oy0, iy0))
    inter = inter_w * inter_h
    inner_area = iw * ih
    return inter / inner_area if inner_area > 0 else 0.0


def _remove_leftover_table_fragments(slide, table_rect: Any, keep_element: Any) -> int:
    """Removes any PICTURE/TEXT_BOX shape (other than the table itself) whose
    bounding box sits almost entirely inside the just-converted table's own
    bounding box - the converter's per-cell background/text fragments that
    would otherwise double up with the new native table's own rendering.
    Only ever called on the success path (never during a rollback), so the
    picture-based fallback rendering is never touched when a table isn't
    actually being kept. Bounded to shapes fully inside the table's own rect
    (not merely overlapping it) specifically so this can never reach outside
    the table and delete unrelated slide content - see this function's
    module-level docstring for why these fragments exist at all."""
    sp_tree = slide.shapes._spTree
    to_remove = []
    for shape in list(slide.shapes):
        if shape._element is keep_element:
            continue
        if shape.shape_type not in _LEFTOVER_FRAGMENT_SHAPE_TYPES:
            continue
        if _containment_ratio(table_rect, _shape_rect(shape)) >= _LEFTOVER_FRAGMENT_CONTAINMENT_MIN:
            to_remove.append(shape._element)
    for element in to_remove:
        sp_tree.remove(element)
    return len(to_remove)


def _replace_picture_with_native_table(
    slide,
    picture_shape,
    captured_table: dict,
    emu_per_px_x: float = 1.0,
    emu_per_px_y: float = 1.0,
) -> bool:
    try:
        sp_tree = slide.shapes._spTree
        picture_element = picture_shape._element
        original_index = list(sp_tree).index(picture_element)
        left, top, width, height = _shape_rect(picture_shape)
        # The flattened picture this table is replacing was produced by the
        # closed-source export converter's own table-flattening pass, whose
        # own box is never validated against the slide canvas anywhere
        # upstream (see _clamp_rect_to_slide's docstring) - a wide,
        # non-`table-layout:fixed` table can genuinely bleed past the slide
        # edge. Clamp before building the native shape so a bleeding table
        # can never carry through unchanged.
        slide_width_emu, slide_height_emu = _slide_dimensions_emu(slide)
        left, top, width, height = _clamp_rect_to_slide(
            (left, top, width, height), slide_width_emu, slide_height_emu
        )
        if width <= 0 or height <= 0:
            LOGGER.info(
                "pptx_native_table_service: skip table (picture box entirely "
                "off-canvas after clamping)"
            )
            return False
        row_count, col_count = captured_table["rowCount"], captured_table["colCount"]

        # The picture must come out of the tree before add_table() can be
        # called (python-pptx has no "build a table, then swap it in" API) -
        # same structural dance as _replace_picture_with_native_chart. Any
        # failure from here through content/merge application (the table's
        # actual structure, not its cosmetics) restores the original picture
        # before re-raising, so "upgrade fails -> table stays a flattened
        # image" holds even when the failure happens after add_table() has
        # already succeeded.
        sp_tree.remove(picture_element)
        graphic_frame = None
        try:
            graphic_frame = slide.shapes.add_table(
                row_count, col_count, left, top, width, height
            )
            # add_table() appends at the end of the tree; move it back to
            # the picture's original position so z-order/stacking is
            # unchanged.
            sp_tree.remove(graphic_frame._element)
            sp_tree.insert(original_index, graphic_frame._element)
            _apply_table_content(graphic_frame.table, captured_table)
            _apply_table_merges(graphic_frame.table, captured_table)
        except Exception:
            if graphic_frame is not None:
                try:
                    sp_tree.remove(graphic_frame._element)
                except ValueError:
                    pass
            sp_tree.insert(original_index, picture_element)
            raise

        try:
            _apply_table_styling(
                graphic_frame.table, captured_table, emu_per_px_x, emu_per_px_y
            )
        except Exception:
            LOGGER.exception(
                "pptx_native_table_service: styling failed, table kept with default styling"
            )

        removed_count = _remove_leftover_table_fragments(
            slide, (left, top, width, height), graphic_frame._element
        )
        if removed_count:
            LOGGER.info(
                "pptx_native_table_service: removed %s leftover picture/text-box "
                "fragment(s) left behind by the converter's own per-cell flattening",
                removed_count,
            )
        return True
    except Exception:
        LOGGER.exception(
            "pptx_native_table_service: failed to build native table for one slide"
        )
        return False


def _try_upgrade_one_table(
    slide,
    captured_table_raw: dict,
    emu_per_px_x: float,
    emu_per_px_y: float,
    claimed_shape_ids: set,
) -> bool:
    captured_table = _build_table_grid(captured_table_raw)
    if captured_table is None:
        LOGGER.info(
            "pptx_native_table_service: skip table (invalid or oversized grid)"
        )
        return False

    bounding_box = captured_table_raw.get("boundingBox")
    if not isinstance(bounding_box, dict):
        LOGGER.info("pptx_native_table_service: skip table (missing boundingBox)")
        return False
    target_rect = _rect_to_emu(bounding_box, emu_per_px_x, emu_per_px_y)
    if target_rect[2] <= 0 or target_rect[3] <= 0:
        LOGGER.info(
            "pptx_native_table_service: skip table (degenerate boundingBox %s)",
            bounding_box,
        )
        return False

    picture_shapes = [
        shape
        for shape in slide.shapes
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE
        and id(shape._element) not in claimed_shape_ids
    ]
    best_shape, best_score, second_score = _best_overlap_match(
        target_rect, picture_shapes
    )
    if best_shape is None:
        LOGGER.info(
            "pptx_native_table_service: skip table (no picture shapes on slide)"
        )
        return False
    if best_score < _IOU_MIN or (best_score - second_score) < _IOU_AMBIGUITY_MARGIN:
        LOGGER.info(
            "pptx_native_table_service: skip table (no confident geometry match: "
            "best_iou=%.3f second_best_iou=%.3f candidates=%s)",
            best_score,
            second_score,
            len(picture_shapes),
        )
        return False

    claimed_shape_ids.add(id(best_shape._element))
    upgraded = _replace_picture_with_native_table(
        slide, best_shape, captured_table, emu_per_px_x, emu_per_px_y
    )
    LOGGER.info(
        "pptx_native_table_service: %s table rows=%s cols=%s iou=%.3f",
        "upgraded" if upgraded else "failed to build native table for",
        captured_table["rowCount"],
        captured_table["colCount"],
        best_score,
    )
    return upgraded


async def upgrade_flattened_tables_to_native(
    pptx_path: str, token: Optional[str], presentation_id: uuid.UUID
) -> None:
    """Best-effort. Never raises. Leaves pptx_path untouched on any failure,
    ambiguity, or absence of captured table data. Must be called strictly
    after the chart-upgrade pass has already run and saved (see Design
    Decision 3 in the table-export plan): a picture removed by a successful
    chart upgrade is no longer MSO_SHAPE_TYPE.PICTURE, so it's naturally
    excluded from this pass's own candidate pool with no shared state
    needed between the two passes."""
    if not token:
        LOGGER.info(
            "pptx_native_table_service: no capture token for this export "
            "(pdf export, or pptx export minted none) - skipping"
        )
        return
    try:
        capture = table_capture_store.take_capture(token)
        if not capture:
            LOGGER.info(
                "pptx_native_table_service: no capture found for token=%s "
                "(the export page's report never arrived, or arrived after "
                "this export finished) - keeping flattened images",
                token,
            )
            return
        tables = capture.get("tables")
        if not isinstance(tables, list) or not tables:
            LOGGER.info(
                "pptx_native_table_service: capture for token=%s had zero tables "
                "- keeping flattened images",
                token,
            )
            return

        tables_by_slide = _group_by_slide_order(tables)
        if not tables_by_slide:
            LOGGER.info(
                "pptx_native_table_service: capture for token=%s had %s table(s) "
                "but none had a usable slideOrderIndex - keeping flattened images",
                token,
                len(tables),
            )
            return

        expected_count = await _expected_slide_count(presentation_id)

        prs = Presentation(pptx_path)
        if expected_count and len(prs.slides) != expected_count:
            LOGGER.warning(
                "pptx_native_table_service: slide count mismatch (pptx=%s, expected=%s), "
                "skipping native table upgrade",
                len(prs.slides),
                expected_count,
            )
            return

        LOGGER.info(
            "pptx_native_table_service: token=%s captured %s table(s) across %s slide(s), "
            "pptx has %s slide(s) - starting native table matching",
            token,
            len(tables),
            len(tables_by_slide),
            len(prs.slides),
        )

        emu_per_px_x = prs.slide_width / _DESIGN_WIDTH_PX
        emu_per_px_y = prs.slide_height / _DESIGN_HEIGHT_PX

        upgraded_count = 0
        for slide_order_index, slide in enumerate(prs.slides):
            slide_tables = tables_by_slide.get(slide_order_index)
            if not slide_tables:
                continue
            claimed_shape_ids: set = set()
            for captured_table in slide_tables:
                if _try_upgrade_one_table(
                    slide,
                    captured_table,
                    emu_per_px_x,
                    emu_per_px_y,
                    claimed_shape_ids,
                ):
                    upgraded_count += 1

        if upgraded_count:
            prs.save(pptx_path)
        LOGGER.info(
            "pptx_native_table_service: upgraded %s of %s captured table(s) to native PPTX tables",
            upgraded_count,
            len(tables),
        )
    except Exception:
        LOGGER.exception(
            "pptx_native_table_service: native table upgrade failed, keeping flattened images"
        )
