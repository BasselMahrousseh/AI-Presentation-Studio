from typing import Any, Optional

from pptx.util import Length, Pt
from sqlmodel import select

from models.sql.slide import SlideModel
from services.database import async_session_maker

# Generic geometry/color/font helpers shared by every "capture live rendered
# data -> match a flattened export picture by position -> swap in a native
# PPTX element" pipeline in this codebase (charts, tables). Moved verbatim
# out of pptx_native_chart_service.py (its original home) when the table
# pipeline was added, since none of this has any chart-specific coupling.
# Behavior-preserving: pptx_native_chart_service.py imports these names
# rather than redefining them, so its own test suite is the regression check
# for this move.

# The frontend capture reports geometry in the same 1280x720 logical canvas
# every slide is designed and exported in (verified against a real
# pptx_model.json debug artifact: picture shape positions sit inside
# 0-1280 / 0-720 with no extra scale factor).
_DESIGN_WIDTH_PX = 1280
_DESIGN_HEIGHT_PX = 720

# A correct geometric match should be near-perfect (no scale correction is
# needed, see above), so a borderline score more likely means a bug (stale
# capture, wrong slide, cropped element) than a legitimate close call -> fail
# closed rather than tune a permissive threshold.
_IOU_MIN = 0.90
_IOU_AMBIGUITY_MARGIN = 0.05

Rect = tuple[int, int, int, int]  # left, top, width, height, all in EMU

# The capture reports font sizes in CSS px within the same 1280x720 logical
# canvas the geometry above is measured in. That canvas is exported at
# 1280px = 13.333in (960pt), so 1 CSS px = 0.75pt exactly - and since every
# captured size is multiplied by a clean 0.75, the conversion is lossless in
# the centipoint units python-pptx's Font.size setter stores (e.g. 14px ->
# 10.5pt -> sz="1050").
_PT_PER_CSS_PX = 0.75
_MIN_FONT_PX = 1.0
_MAX_FONT_PX = 200.0


def _parse_oklab(text: str) -> Optional[tuple[float, float, float, Optional[float]]]:
    """Parses a CSS Color 4 `oklab(L a b)` or `oklab(L a b / A)` string into
    its raw (L, a, b, alpha) components, or None if malformed. `L` and `A`
    may be plain numbers or percentages (0%-100%, mapped to 0.0-1.0); `a`/`b`
    are always plain (possibly negative) numbers - never percentages in
    practice for the colors this pipeline ever sees."""
    if not text.startswith("oklab(") or not text.endswith(")"):
        return None
    inner = text[len("oklab(") : -1]
    if "/" in inner:
        components_part, _, alpha_part = inner.partition("/")
        alpha_part = alpha_part.strip()
    else:
        components_part, alpha_part = inner, None
    parts = components_part.split()
    if len(parts) != 3:
        return None

    def _parse_number(raw: str) -> Optional[float]:
        raw = raw.strip()
        try:
            if raw.endswith("%"):
                return float(raw[:-1]) / 100.0
            return float(raw)
        except ValueError:
            return None

    L, a, b = (_parse_number(p) for p in parts)
    if L is None or a is None or b is None:
        return None
    alpha: Optional[float] = None
    if alpha_part is not None:
        alpha = _parse_number(alpha_part)
        if alpha is None:
            return None
    return L, a, b, alpha


def _srgb_channel_from_linear(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (value ** (1 / 2.4)) - 0.055


def _oklab_to_hex(L: float, a: float, b: float) -> str:
    """OKLab -> linear sRGB -> gamma-encoded sRGB, using the standard
    matrices from the CSS Color Module 4 spec / Björn Ottosson's reference
    OKLab implementation (https://bottosson.github.io/posts/oklab/) - the
    same matrices browsers themselves use, so this reproduces what a real
    browser would have rendered for the color rather than an approximation.
    Verified against the two values that are trivially checkable regardless
    of matrix precision: oklab(0 0 0) -> pure black, oklab(1 0 0) -> pure
    white. Channels are clamped to the valid sRGB range - out-of-gamut OKLab
    values (rare for the colors this pipeline ever captures) clip rather
    than wrap or error."""
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l, m, s = l_**3, m_**3, s_**3

    r_lin = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g_lin = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b_lin = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    def _channel_byte(linear: float) -> int:
        return max(0, min(255, round(_srgb_channel_from_linear(linear) * 255)))

    r, g, bl = _channel_byte(r_lin), _channel_byte(g_lin), _channel_byte(b_lin)
    return f"{r:02X}{g:02X}{bl:02X}"


def _hex_from_css_color(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("#"):
        hex_part = text[1:]
        if len(hex_part) == 3:
            hex_part = "".join(ch * 2 for ch in hex_part)
        if len(hex_part) == 6 and all(
            ch in "0123456789abcdefABCDEF" for ch in hex_part
        ):
            return hex_part.upper()
        return None
    if text.startswith("rgb"):
        try:
            inner = text[text.index("(") + 1 : text.index(")")]
            parts = [p.strip() for p in inner.split(",")]
            r, g, b = (int(float(p)) for p in parts[:3])
        except (ValueError, IndexError):
            return None
        if all(0 <= c <= 255 for c in (r, g, b)):
            return f"{r:02X}{g:02X}{b:02X}"
        return None
    if text.startswith("oklab("):
        # A real, previously-undetected gap: for a CSS color built from an
        # opacity modifier (Tailwind's `border-black/15`, `bg-white/50`,
        # etc.), Chrome's own getComputedStyle can serialize the resolved
        # color as `oklab(...)` rather than `rgba(...)` - confirmed against a
        # real user's own generated deck, where every solid rgb()/rgba()
        # color (no opacity modifier) captured correctly, but a `/15`
        # opacity-modified border color captured as `oklab(0 0 0 / 0.15)`
        # and was silently dropped, since neither this function nor
        # _alpha_from_css_color recognized the format at all. Converting it
        # properly (rather than only special-casing the achromatic
        # black/white case actually seen) protects every other color this
        # pipeline captures - background, text, chart colors - from the same
        # silent loss if a future deck's opacity-modified color isn't black.
        parsed = _parse_oklab(text)
        if parsed is None:
            return None
        L, a, b, _alpha = parsed
        return _oklab_to_hex(L, a, b)
    return None


def _alpha_from_css_color(value: Any) -> Optional[float]:
    """The alpha component of an `rgba(r, g, b, a)` or `oklab(L a b / a)`
    string, or None for anything else (an opaque color, malformed input, or
    a=1). Kept deliberately separate from _hex_from_css_color rather than
    changing that function's return shape - several call sites (and its own
    pinned tests) depend on its existing "6-hex-or-None" contract. 8-digit
    #RRGGBBAA is not handled here because _hex_from_css_color already
    rejects any hex string that isn't 3 or 6 characters, so such a color
    never reaches a fill site to begin with; the two would need to change
    together if that ever does."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("oklab("):
        parsed = _parse_oklab(text)
        if parsed is None:
            return None
        _, _, _, alpha = parsed
        if alpha is None or not (0.0 <= alpha < 1.0):
            return None
        return alpha
    if not text.startswith("rgb"):
        return None
    try:
        inner = text[text.index("(") + 1 : text.index(")")]
        parts = [p.strip() for p in inner.split(",")]
        alpha = float(parts[3])
    except (ValueError, IndexError):
        return None
    if not (0.0 <= alpha < 1.0):
        # >=1.0 is opaque - nothing to inject; out-of-range is malformed, and
        # failing to today's opaque behavior beats emitting an invalid
        # ST_PositivePercentage into the file.
        return None
    return alpha


def _pt_from_css_px(value: Any) -> Optional[Length]:
    """Convert a captured CSS-px font size to a python-pptx `Length` in
    points, or None if the value is absent/invalid. Never raises - a garbage
    captured size (out of range, non-numeric, NaN/inf) must fall back to
    PowerPoint's own default rather than corrupt or crash the export."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN/inf
        return None
    if not (_MIN_FONT_PX <= value <= _MAX_FONT_PX):
        return None
    return Pt(value * _PT_PER_CSS_PX)


def _rect_to_emu(rect: dict, emu_per_px_x: float, emu_per_px_y: float) -> Rect:
    left = int(round(float(rect.get("left", 0)) * emu_per_px_x))
    top = int(round(float(rect.get("top", 0)) * emu_per_px_y))
    width = int(round(float(rect.get("width", 0)) * emu_per_px_x))
    height = int(round(float(rect.get("height", 0)) * emu_per_px_y))
    return left, top, width, height


def _shape_rect(shape) -> Rect:
    return shape.left, shape.top, shape.width, shape.height


def _clamp_rect_to_slide(
    rect: Rect, slide_width_emu: int, slide_height_emu: int
) -> Rect:
    """Shrink `rect` (left, top, width, height, all EMU) so it never extends
    past the slide's own right/bottom edge, without moving its top-left
    anchor.

    Both native-table and native-chart placement inherit their final
    left/top/width/height from a flattened picture the closed-source export
    converter already produced (see `_replace_picture_with_native_table`/
    `_replace_picture_with_native_chart`), and that picture's own box is
    never itself validated against the slide canvas anywhere in this
    pipeline - a table wider than its intended column (e.g. a browser's
    automatic, non-`table-layout:fixed` sizing of a wide multi-column
    comparison table) can produce a picture, and therefore a native shape,
    that genuinely extends past x=1280/y=720. This is a last-resort backstop
    for exactly that case: it only ever shrinks an already-too-large box down
    to the canvas edge, so a shape that was already correctly sized is
    returned completely unchanged. Anchored at the existing top-left rather
    than rescaled proportionally, matching how a native table/chart's
    content is captured (top-left-anchored rows/columns), not centered."""
    left, top, width, height = rect
    max_width = max(slide_width_emu - left, 0)
    max_height = max(slide_height_emu - top, 0)
    return left, top, min(width, max_width), min(height, max_height)


def _slide_dimensions_emu(slide) -> tuple[int, int]:
    """Return the real (slide_width, slide_height) in EMU for the
    Presentation a given Slide belongs to.

    Deliberately navigated from the slide itself (`slide.part.package
    .presentation_part.presentation`) rather than taking `emu_per_px_x/y` as
    a proxy for slide size (`_DESIGN_WIDTH_PX * emu_per_px_x`): several
    existing callers pass those scale factors as their unscaled 1.0 default
    when they don't otherwise need them, while still placing shapes at real,
    fully-scaled EMU coordinates - multiplying a real coordinate against a
    1.0 default would produce a nonsensical (tiny) "slide size" and clamp
    away content that was never actually off-canvas. Reading the dimensions
    straight from the presentation is correct regardless of what scale
    factor any particular caller happens to have on hand."""
    presentation = slide.part.package.presentation_part.presentation
    return presentation.slide_width, presentation.slide_height


def _iou(a: Rect, b: Rect) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    inter_w = max(0, min(ax1, bx1) - max(ax0, bx0))
    inter_h = max(0, min(ay1, by1) - max(ay0, by0))
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def _best_overlap_match(
    target_rect: Rect, picture_shapes: list
) -> tuple[Optional[Any], float, float]:
    scored = sorted(
        ((_iou(target_rect, _shape_rect(shape)), shape) for shape in picture_shapes),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored:
        return None, 0.0, 0.0
    best_score, best_shape = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    return best_shape, best_score, second_score


def _group_by_slide_order(items: list) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("slideOrderIndex")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        grouped.setdefault(index, []).append(item)
    return grouped


async def _expected_slide_count(presentation_id) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(SlideModel.id).where(SlideModel.presentation == presentation_id)
        )
        return len(result.all())
