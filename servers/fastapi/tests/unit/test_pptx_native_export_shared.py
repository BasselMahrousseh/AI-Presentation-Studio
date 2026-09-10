import pytest

from services import pptx_native_export_shared as shared

# Pure-function tests for the geometry/color/font-conversion helpers shared
# by every "capture live rendered data -> match a flattened export picture by
# position -> swap in a native PPTX element" pipeline (charts, tables).
# pptx_native_chart_service.py imports these names rather than redefining
# them - its own test suite (test_pptx_native_chart_service.py) is what
# proves that re-export didn't change chart behavior. These tests exercise
# the shared implementation directly.


# ---------------------------------------------------------------------------
# Color parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("#ff0000", "FF0000"),
        ("#F00", "FF0000"),
        ("rgb(0, 128, 255)", "0080FF"),
        ("rgba(10, 20, 30, 0.5)", "0A141E"),
        ("not-a-color", None),
        (None, None),
        (123, None),
        ("#12345", None),
    ],
)
def test_hex_from_css_color(value, expected):
    assert shared._hex_from_css_color(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("rgba(53, 208, 186, 0.28)", 0.28),
        ("rgba(0,0,0,0)", 0.0),
        ("rgba(1,2,3,1)", None),
        ("rgba(1,2,3,1.0)", None),
        ("rgb(1,2,3)", None),
        ("#FF0000", None),
        ("rgba(1,2,3,bad)", None),
        ("rgba(1,2,3,2)", None),
        ("rgba(1,2,3,-1)", None),
        (None, None),
        (123, None),
    ],
)
def test_alpha_from_css_color(value, expected):
    result = shared._alpha_from_css_color(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# oklab() color parsing - a real gap found via a live user report: Chrome's
# getComputedStyle can serialize an opacity-modified color (Tailwind's
# `border-black/15`, `bg-white/50`, etc.) as `oklab(...)` rather than
# `rgba(...)`, which neither _hex_from_css_color nor _alpha_from_css_color
# recognized at all before this - silently dropping the color rather than
# raising, so the failure mode was invisible (a missing style, not an error).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected_hex",
    [
        ("oklab(0 0 0)", "000000"),
        ("oklab(0 0 0 / 0.15)", "000000"),
        ("oklab(1 0 0)", "FFFFFF"),
        ("oklab(1 0 0 / 1)", "FFFFFF"),
        ("oklab(0.5 0 0 / 50%)", "636363"),
        ("oklab(", None),
        ("oklab()", None),
        ("oklab(not a color)", None),
        ("oklab(0 0)", None),  # only 2 components
    ],
)
def test_hex_from_css_color_parses_oklab(value, expected_hex):
    assert shared._hex_from_css_color(value) == expected_hex


@pytest.mark.parametrize(
    "value,expected_alpha",
    [
        ("oklab(0 0 0 / 0.15)", 0.15),
        ("oklab(0.5 0 0 / 50%)", 0.5),
        ("oklab(0 0 0)", None),  # no alpha component -> opaque
        ("oklab(0 0 0 / 1)", None),  # fully opaque -> nothing to inject
        ("oklab(0 0 0 / 2)", None),  # out of range -> malformed
        ("oklab(0 0 0 / bad)", None),
    ],
)
def test_alpha_from_css_color_parses_oklab(value, expected_alpha):
    result = shared._alpha_from_css_color(value)
    if expected_alpha is None:
        assert result is None
    else:
        assert result == pytest.approx(expected_alpha)


def test_oklab_black_and_white_are_exact_regardless_of_matrix_precision():
    """The one property of the OKLab->sRGB conversion that's true regardless
    of any rounding in the underlying matrices: L=0 with no chroma is always
    pure black, and L=1 with no chroma is always pure white."""
    assert shared._oklab_to_hex(0.0, 0.0, 0.0) == "000000"
    assert shared._oklab_to_hex(1.0, 0.0, 0.0) == "FFFFFF"


# ---------------------------------------------------------------------------
# Font size conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "px,expected_pt",
    [(13, 9.75), (14, 10.5), (18, 13.5), (1.0, 0.75), (200, 150.0)],
)
def test_pt_from_css_px(px, expected_pt):
    result = shared._pt_from_css_px(px)
    assert result is not None
    assert result.pt == pytest.approx(expected_pt)


@pytest.mark.parametrize(
    "value",
    [None, "14", True, False, float("nan"), float("inf"), float("-inf"), 0, -3, 5000, {}],
)
def test_pt_from_css_px_rejects_invalid_input(value):
    assert shared._pt_from_css_px(value) is None


# ---------------------------------------------------------------------------
# Geometry matching
# ---------------------------------------------------------------------------


def test_iou_exact_overlap_is_one():
    rect = (0, 0, 100, 100)
    assert shared._iou(rect, rect) == pytest.approx(1.0)


def test_iou_no_overlap_is_zero():
    assert shared._iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_iou_partial_overlap():
    a = (0, 0, 100, 100)
    b = (50, 0, 100, 100)
    # intersection 50x100=5000, union 100*100*2-5000=15000
    assert shared._iou(a, b) == pytest.approx(5000 / 15000)


class _FakeShape:
    def __init__(self, left, top, width, height):
        self.left, self.top, self.width, self.height = left, top, width, height
        self._element = object()


def test_best_overlap_match_picks_highest_scoring_confident_match():
    target = (0, 0, 100, 100)
    exact = _FakeShape(0, 0, 100, 100)
    far = _FakeShape(1000, 1000, 100, 100)
    best, best_score, second_score = shared._best_overlap_match(target, [far, exact])
    assert best is exact
    assert best_score == pytest.approx(1.0)
    assert second_score == 0.0


def test_best_overlap_match_no_candidates_returns_none():
    best, best_score, second_score = shared._best_overlap_match((0, 0, 10, 10), [])
    assert best is None
    assert best_score == 0.0
    assert second_score == 0.0


def test_rect_to_emu_scales_and_rounds():
    rect = shared._rect_to_emu(
        {"left": 10, "top": 20, "width": 30, "height": 40}, emu_per_px_x=2.5, emu_per_px_y=2.5
    )
    assert rect == (25, 50, 75, 100)


def test_shape_rect_reads_left_top_width_height():
    shape = _FakeShape(1, 2, 3, 4)
    assert shared._shape_rect(shape) == (1, 2, 3, 4)


# ---------------------------------------------------------------------------
# Grouping by slide order
# ---------------------------------------------------------------------------


def test_group_by_slide_order():
    items = [
        {"slideOrderIndex": 0, "kind": "bar"},
        {"slideOrderIndex": 0, "kind": "line"},
        {"slideOrderIndex": 2, "kind": "pie"},
        {"slideOrderIndex": "not-an-int", "kind": "bad"},
        "not-a-dict",
    ]
    grouped = shared._group_by_slide_order(items)
    assert set(grouped.keys()) == {0, 2}
    assert len(grouped[0]) == 2
    assert len(grouped[2]) == 1
