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
