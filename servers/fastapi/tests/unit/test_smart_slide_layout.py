from utils.smart_slide_layout import inspect_smart_slide_layout


# Real HTML pulled from a generated slide (app_data/fastapi.db, slide id
# 58ec19bf15764bcebbf0f5a134fbc818) that visibly overflowed in production: a
# `min-h-0`-marked two-column row (`grid-cols-[0.88fr_1.12fr]`) inside a flex
# column whose height is implied by `position: absolute` with both `top-*`
# and `bottom-*` set (never an explicit `h-*` class). Its red card child has
# no `min-h-0` of its own, so when the row is compressed to fit, the card's
# real content overflows past it and collides with the "Governance rhythm"
# row that follows in the same flex column.
_REAL_OVERFLOWING_SLIDE = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-[64px] right-[64px] top-[72px] bottom-[96px] flex flex-col">
    <div class="flex items-end justify-between gap-10">
      <h2 class="mt-4 text-[43px] font-bold">Run net zero with disciplined governance</h2>
      <p class="max-w-[430px] text-[18px]">Embed the transition in everyday management.</p>
    </div>
    <div class="mt-7 grid min-h-0 grid-cols-[0.88fr_1.12fr] gap-6">
      <div class="bg-[#E00600] px-6 py-6 text-white">
        <p class="text-[15px] font-semibold uppercase">Leadership commitment</p>
        <p class="mt-4 text-[28px] font-bold">Treat emissions outcomes as a core business measure within strategy, capital allocation, sourcing and performance reviews.</p>
        <div class="mt-6 border-t border-white pt-5">
          <p class="text-[15px] font-semibold uppercase">Intervene when</p>
          <p class="mt-2 text-[17px]">Milestones slip, evidence weakens or business choices create material risk to the transition plan.</p>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div><h3 class="text-[23px] font-bold">Assign clear ownership</h3><p class="mt-2 text-[16px]">Define decision rights.</p></div>
        <div><h3 class="text-[23px] font-bold">Watch early signals</h3><p class="mt-2 text-[16px]">Use energy metrics.</p></div>
        <div><h3 class="text-[23px] font-bold">Test the evidence</h3><p class="mt-2 text-[16px]">Validate source data.</p></div>
        <div><h3 class="text-[23px] font-bold">Course-correct quickly</h3><p class="mt-2 text-[16px]">Shift investment.</p></div>
      </div>
    </div>
    <div class="mt-5 grid grid-cols-[190px_1fr_1fr_1fr] items-center border border-[#0B1F3A] px-5 py-4">
      <p class="text-[15px] font-bold uppercase">Governance rhythm</p>
      <p class="text-[16px] font-semibold">Monthly · execution</p>
      <p class="text-[16px] font-semibold">Quarterly · investment</p>
      <p class="text-[16px] font-semibold">Annually · ambition and plan</p>
    </div>
  </div>
</section>
"""


def _has_shrink_marked_grid_issue(html: str) -> bool:
    return any(
        "min-h-0`-marked" in issue for issue in inspect_smart_slide_layout(html)
    )


def test_real_overflowing_slide_is_flagged():
    assert _has_shrink_marked_grid_issue(_REAL_OVERFLOWING_SLIDE)


def test_column_without_effective_fixed_height_is_not_flagged():
    without_fixed_height = _REAL_OVERFLOWING_SLIDE.replace(
        'class="absolute left-[64px] right-[64px] top-[72px] bottom-[96px] flex flex-col"',
        'class="relative flex flex-col"',
    )
    assert not _has_shrink_marked_grid_issue(without_fixed_height)


def test_row_without_min_h_0_is_not_flagged():
    without_min_h_0 = _REAL_OVERFLOWING_SLIDE.replace(
        'class="mt-7 grid min-h-0 grid-cols-[0.88fr_1.12fr] gap-6"',
        'class="mt-7 grid grid-cols-[0.88fr_1.12fr] gap-6"',
    )
    assert not _has_shrink_marked_grid_issue(without_min_h_0)


def test_short_row_with_no_later_sibling_is_not_flagged():
    short_row_only = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-[64px] right-[64px] top-[72px] bottom-[96px] flex flex-col">
    <div class="mt-7 grid min-h-0 grid-cols-[0.88fr_1.12fr] gap-6">
      <div class="bg-[#E00600] px-6 py-6 text-white">
        <p>Short heading</p>
        <p>Short body text.</p>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div><p>Item one</p></div>
        <div><p>Item two</p></div>
      </div>
    </div>
  </div>
</section>
"""
    assert not _has_shrink_marked_grid_issue(short_row_only)


def test_existing_numbered_grid_shrink_to_fit_check_is_unaffected():
    # The pre-existing pattern _find_shrink_to_fit_overflow_risks protects:
    # explicit h-[Npx], flex-1 min-h-0, numbered grid-cols-N (N>=3).
    numbered_grid_pattern = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="flex flex-col h-[500px]">
    <div class="flex-1 min-h-0 grid grid-cols-3 gap-4">
      <div><p>Card one with a longer body describing something important.</p></div>
      <div><p>Card two</p></div>
      <div><p>Card three</p></div>
    </div>
    <div><p>Footer content that comes after the grid row.</p></div>
  </div>
</section>
"""
    issues = inspect_smart_slide_layout(numbered_grid_pattern)
    assert any("shrink-to-fit" in issue for issue in issues)


# --- _find_stacked_list_overflow_risks ("heuristic D") ---------------------
#
# This heuristic had zero test coverage until it took down a real production
# generation (see CLAUDE.md): a pure item-count shape-match with no regard
# for how much text those items actually held. Verified directly against this
# app's own database of 179 already-shipped slides that height-matched
# flex-column panels split cleanly as 2 items -> 19 panels, 3 items -> 27
# panels (up to 1104 combined characters, accepted fine), 4+ items -> 0
# panels ever - a hard, count-only ban, not a real overflow boundary. These
# tests pin the fixed version: item count is now only a cheap precondition,
# and real text volume against the panel's own resolved size (or a flat
# calibrated fallback) is what actually decides it.


def _has_stacked_list_issue(html: str) -> bool:
    return any(
        "height-matched panel" in issue for issue in inspect_smart_slide_layout(html)
    )


def _stacked_panel_html(items: list[str], *, panel_classes: str, decorative: bool = False) -> str:
    attrs = ' aria-hidden="true"' if decorative else ""
    item_html = "".join(f"<div>{text}</div>" for text in items)
    return f"""
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="{panel_classes}"{attrs}>{item_html}</div>
</section>
"""


# ~324 characters - long enough that 4 of them clearly exceeds any capacity
# this module would compute, short enough that 2-3 of them stay well under
# every threshold used below.
_LONG_ITEM_TEXT = (
    "Revenue grew twenty four percent year over year across every single "
    "one of our regional business units, driven primarily by strong "
    "enterprise demand and continued momentum across every product line "
    "we shipped this fiscal year and the next. "
) * 2


def test_narrow_panel_with_long_stacked_items_is_flagged():
    # A real overflow case: 4 long items in a narrow (200px) fixed-width,
    # full-height panel. The per-pixel capacity model (shared with heuristic
    # C) resolves both dimensions here, so this is checked precisely rather
    # than falling back to the flat threshold.
    html = _stacked_panel_html(
        [_LONG_ITEM_TEXT] * 4,
        panel_classes="flex flex-col h-full w-[200px] gap-4",
    )
    assert _has_stacked_list_issue(html)


def test_benign_short_four_item_rail_is_not_flagged():
    # The exact false positive that used to ship: an ordinary 4-bullet
    # full-height side rail, nowhere near overflowing. Before the volume
    # gate, item count alone flagged this.
    short_items = [
        "Revenue grew 24% year over year",
        "Churn fell to 3.1% in Q4 overall",
        "Net retention reached 118 percent",
        "Enterprise seats up 40% this year",
    ]
    html = _stacked_panel_html(
        short_items, panel_classes="flex flex-col h-full w-[380px] gap-4"
    )
    assert not _has_stacked_list_issue(html)


def test_three_stacked_items_are_not_flagged_even_with_long_text():
    # _MIN_STACKED_LIST_ITEMS = 4 is a precondition, not just a starting
    # point: even well past any text-volume threshold, 3 items never trip
    # this heuristic, matching every 3-item panel ever accepted in
    # production.
    html = _stacked_panel_html(
        [_LONG_ITEM_TEXT] * 3,
        panel_classes="flex flex-col h-full w-[200px] gap-4",
    )
    assert not _has_stacked_list_issue(html)


def test_items_below_the_text_threshold_are_not_counted_as_items():
    # _MIN_ITEM_TEXT_CHARACTERS = 20: an item block shorter than this isn't
    # treated as a "stacked item" at all, so 4 of them never reach the
    # item-count precondition in the first place.
    html = _stacked_panel_html(
        ["Alpha", "Beta", "Gamma", "Delta"],
        panel_classes="flex flex-col h-full w-[200px] gap-4",
    )
    assert not _has_stacked_list_issue(html)


def test_panel_without_an_imposed_height_is_not_flagged():
    html = _stacked_panel_html(
        [_LONG_ITEM_TEXT] * 4, panel_classes="flex flex-col w-[200px] gap-4"
    )
    assert not _has_stacked_list_issue(html)


def test_self_stretch_panel_over_the_flat_threshold_is_flagged():
    # self-stretch imposes a height but resolves to no pixel number anywhere
    # in the static analysis, so this exercises the flat
    # _MIN_STACKED_LIST_TEXT_CHARACTERS fallback rather than the per-pixel
    # capacity model.
    html = _stacked_panel_html(
        [_LONG_ITEM_TEXT] * 4, panel_classes="flex flex-col self-stretch gap-4"
    )
    assert _has_stacked_list_issue(html)


def test_self_stretch_panel_under_the_flat_threshold_is_not_flagged():
    short_items = [
        "Revenue grew 24% year over year",
        "Churn fell to 3.1% in Q4 overall",
        "Net retention reached 118 percent",
        "Enterprise seats up 40% this year",
    ]
    html = _stacked_panel_html(
        short_items, panel_classes="flex flex-col self-stretch gap-4"
    )
    assert not _has_stacked_list_issue(html)


def test_decorative_panel_is_not_flagged():
    html = _stacked_panel_html(
        [_LONG_ITEM_TEXT] * 4,
        panel_classes="flex flex-col h-full w-[200px] gap-4",
        decorative=True,
    )
    assert not _has_stacked_list_issue(html)


def test_nested_list_wrapper_items_are_counted():
    # A panel commonly wraps its list in its own flex-col container alongside
    # sibling heading/label elements - _stacked_items looks one level into
    # such a wrapper. Pins that this nested reading also goes through the
    # volume gate (not just the direct-children reading).
    item_html = "".join(f"<div>{_LONG_ITEM_TEXT}</div>" for _ in range(4))
    html = f"""
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="flex flex-col h-full w-[200px] gap-4">
    <p>Label</p>
    <h3>Heading</h3>
    <div class="flex flex-col gap-2">{item_html}</div>
  </div>
</section>
"""
    assert _has_stacked_list_issue(html)


# --- e& footer furniture collision guard -----------------------------------
#
# _check_smart_slide_layout (the render-based pixel checker) runs BEFORE
# apply_smart_brand_template splices the real e& logo/"Confidential"
# label/footer-bar onto a content slide - so the HTML this static check
# inspects never contains that real furniture, and its rectangles must come
# from fixed constants instead. These tests build slides in exactly that
# pre-splice shape: no eand-logo/eand-confidential/eand-footer-bar markup
# present, matching what the check actually sees in production.


def _has_furniture_collision_issue(html: str, *, check_eand_footer: bool) -> bool:
    return any(
        "logo or 'Confidential' label" in issue
        for issue in inspect_smart_slide_layout(
            html, check_eand_footer=check_eand_footer
        )
    )


# The real slide that motivated this guard (app_data/fastapi.db, presentation
# 80c919a9a54f45c9af4a2d3040e185a6, slide index 1): a full-height decorative
# side rail that the e& brand prompt explicitly encourages
# (smart_brand_templates.py's "full-height side rail" guidance). Before this
# guard existed, the render-based pixel checker (which has no concept of
# "decorative") counted this rail as a 90px intrusion into the reserved
# y=630-720 footer band and downscaled the entire slide to 0.875 to "fix" a
# collision that was never real - the rail runs at x=0..12, nowhere near the
# logo (x=32.6..70.1) or the "Confidential" label (x=602.5..677.4).
_REAL_FULL_HEIGHT_RAIL_SLIDE = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-0 top-0 h-[720px] w-3 bg-[#E00600]" aria-hidden="true" data-decorative="true"></div>
  <h1 class="relative ml-16 mt-12 text-[48px] font-bold">Slide title</h1>
</section>
"""


def test_full_height_side_rail_does_not_collide_with_footer_furniture():
    assert not _has_furniture_collision_issue(
        _REAL_FULL_HEIGHT_RAIL_SLIDE, check_eand_footer=True
    )


def test_decorative_layer_over_the_logo_is_flagged():
    html = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-[20px] top-[650px] h-[50px] w-[60px] bg-black" aria-hidden="true" data-decorative="true"></div>
</section>
"""
    assert _has_furniture_collision_issue(html, check_eand_footer=True)


def test_decorative_layer_over_the_confidential_label_is_flagged():
    html = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-[590px] top-[695px] h-[30px] w-[100px] bg-black" aria-hidden="true" data-decorative="true"></div>
</section>
"""
    assert _has_furniture_collision_issue(html, check_eand_footer=True)


def test_decorative_layer_over_only_the_footer_bar_is_not_flagged():
    # The footer bar image itself is fully opaque and painted above all slide
    # content (z-50), so anything drawn beneath it is completely hidden and
    # harmless - unlike the logo/label, which are not full coverage over
    # their own bounding boxes. This is why the footer bar band is
    # deliberately excluded from the guard rectangles.
    html = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-[400px] top-[715px] h-[5px] w-[100px] bg-black" aria-hidden="true" data-decorative="true"></div>
</section>
"""
    assert not _has_furniture_collision_issue(html, check_eand_footer=True)


def test_furniture_guard_is_skipped_when_check_eand_footer_is_false():
    # Standard (non-e&) generation never splices this furniture onto a slide
    # at all, so the guard must not fire there even for identical geometry.
    html = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <div class="absolute left-[20px] top-[650px] h-[50px] w-[60px] bg-black" aria-hidden="true" data-decorative="true"></div>
</section>
"""
    assert not _has_furniture_collision_issue(html, check_eand_footer=False)


def test_non_decorative_content_over_the_logo_area_is_not_flagged_by_this_guard():
    # The guard only inspects decorative, positioned layers - real content
    # placed there is a different (and already-existing) class of problem,
    # not this one.
    html = """
<section class="relative h-[720px] w-[1280px] overflow-hidden bg-white">
  <p class="absolute left-[20px] top-[650px]">Real visible text</p>
</section>
"""
    assert not _has_furniture_collision_issue(html, check_eand_footer=True)
