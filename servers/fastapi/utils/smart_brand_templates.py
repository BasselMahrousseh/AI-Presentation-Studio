"""Fixed brand shells applied after Smart Mode generates the slide content."""

from __future__ import annotations

import html
import re

from fastapi import HTTPException


EAND_SMART_TEMPLATE_ID = "eand"
EAND_FIXED_SLIDE_COUNT = 2
EAND_TITLE_SUBTITLE = "e& presentation"
SUPPORTED_SMART_TEMPLATE_IDS = frozenset({EAND_SMART_TEMPLATE_ID})

_SECTION_CLOSE_RE = re.compile(r"</section>\s*$", re.IGNORECASE)

_EAND_FOOTER_HTML = """
<!-- Fixed e& brand shell; this markup is not model-generated. -->
<div data-brand-template-element="eand-confidential" data-decorative="true"
  class="absolute left-[602.5px] top-[699.2px] z-50 flex h-[20.8px] w-[74.9px] flex-col justify-center"
  aria-hidden="true">
  <div class="text-center" style="font-size:10.7px;line-height:1">
    <span class="text-[10.7px] text-[#000000]">Confidential</span>
  </div>
</div>
<div data-brand-template-element="eand-footer-bar" data-decorative="true"
  class="absolute left-0 top-[711.9px] z-50 h-[9.3px] w-[1280px]" aria-hidden="true">
  <img src="/smart-templates/eand/eand-footer-bar.png" alt="" class="h-full w-full" style="display:block;object-fit:fill;max-width:none;max-height:none">
</div>
<div data-brand-template-element="eand-logo" data-decorative="true"
  class="absolute left-[32.6px] top-[662.9px] z-50 h-[35px] w-[37.7px]" aria-hidden="true">
  <img src="/smart-templates/eand/eand-logo.png" alt="" class="h-full w-full" style="display:block;object-fit:fill;max-width:none;max-height:none">
</div>
""".strip()


def build_eand_title_slide(title: str, subtitle: str) -> str:
    """Return the supplied e& title-slide design with escaped presentation text."""
    safe_title = html.escape(_compact_text(title, "Presentation", 66), quote=True)
    safe_subtitle = html.escape(
        _compact_text(subtitle, "e& presentation", 92), quote=True
    )
    title_size = _title_font_size(title)
    return f"""
<section data-slide-type="title" data-slide-title="{safe_title}"
  class="relative h-[720px] w-[1280px] overflow-hidden bg-[#E00600]">
  <div data-brand-template-element="eand-title-confidential" data-decorative="true"
    class="absolute left-[602.5px] top-[699.2px] z-20 flex h-[20.8px] w-[74.9px] flex-col justify-center" aria-hidden="true">
    <div class="text-center" style="font-size:10.7px;line-height:1"><span class="text-[10.7px] text-[#000000]">Confidential</span></div>
  </div>
  <img data-brand-template-element="eand-title-gradient" src="/smart-templates/eand/eand-title-gradient.png" alt=""
    class="absolute left-[170px] top-[604px] z-10 h-[56px] w-[1109.7px]" style="object-fit:fill;max-width:none;max-height:none" aria-hidden="true">
  <div data-brand-template-element="eand-title-confidential-label" class="absolute left-[1075.9px] top-[678.1px] z-20 w-[174.6px] text-right" aria-hidden="true"
    style="font-size:9.8px;line-height:1.36;color:#4D0F24">Proprietary &amp; Confidential</div>
  <img data-brand-template-element="eand-title-logo" src="/smart-templates/eand/eand-title-logo-white.png" alt="e&amp; etisalat and"
    class="absolute left-[32.7px] top-[583.3px] z-20 h-[105.3px] w-[113.2px]" style="object-fit:cover;object-position:50% 50%">
  <h1 class="absolute left-[20.1px] top-[28px] z-20 m-0 w-[1124.5px] font-bold text-white"
    style="font-family:Arial,sans-serif;font-size:{title_size}px;line-height:1">{safe_title}</h1>
  <p class="absolute left-[20.3px] top-[154px] z-20 m-0 w-[1124.5px] text-white"
    style="font-family:Arial,sans-serif;font-size:42px;line-height:1.15">{safe_subtitle}</p>
</section>
""".strip()


def build_eand_thank_you_slide() -> str:
    """Return the supplied e& thank-you-slide design unchanged."""
    return """
<section data-slide-type="closing" data-slide-title="Thank you"
  class="relative h-[720px] w-[1280px] overflow-hidden bg-[#FFFFFF]">
  <img data-brand-template-element="eand-thank-you-background" src="/smart-templates/eand/eand-thank-you-background.png" alt=""
    class="absolute left-0 top-0 z-0 h-[720px] w-[1280px]" style="object-fit:fill;max-width:none;max-height:none" aria-hidden="true">
  <div data-brand-template-element="eand-thank-you-confidential" class="absolute left-[602.5px] top-[699.2px] z-20 flex h-[20.8px] w-[74.9px] flex-col justify-center" aria-hidden="true">
    <div class="text-center" style="font-size:10.7px;line-height:1"><span class="text-[10.7px] text-[#000000]">Confidential</span></div>
  </div>
  <h1 class="absolute left-[917.8px] top-[353px] z-20 m-0 w-[262.6px] font-bold text-[#E00600]"
    style="font-family:Arial,sans-serif;font-size:46.2px;line-height:1">Thank you</h1>
</section>
""".strip()


def _compact_text(value: str, fallback: str, maximum: int) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        return fallback
    if len(normalized) <= maximum:
        return normalized
    truncated = normalized[: maximum - 1].rsplit(" ", 1)[0].strip()
    return f"{truncated or normalized[: maximum - 3].strip()}..."


def _title_font_size(title: str) -> int:
    length = len(" ".join(str(title or "").split()))
    if length <= 22:
        return 96
    if length <= 36:
        return 72
    if length <= 52:
        return 58
    return 48


def normalize_smart_template_id(value: str | None) -> str | None:
    """Return a known template id, rejecting unknown client input."""
    if value is None:
        return None
    template_id = value.strip().lower()
    if not template_id:
        return None
    if template_id not in SUPPORTED_SMART_TEMPLATE_IDS:
        raise HTTPException(status_code=400, detail="Unknown Smart brand template")
    return template_id


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_SMART_BRAND_COLORS = 4


def normalize_smart_brand_colors(values: list[str] | None) -> list[str] | None:
    """Return validated, deduplicated `#RRGGBB` colors, rejecting malformed
    client input rather than silently dropping or reflowing it into the
    generation prompt."""
    if not values:
        return None
    normalized: list[str] = []
    for value in values:
        candidate = (value or "").strip()
        if not _HEX_COLOR_RE.match(candidate):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid brand color {value!r}; expected #RRGGBB",
            )
        upper = candidate.upper()
        if upper not in normalized:
            normalized.append(upper)
    if len(normalized) > MAX_SMART_BRAND_COLORS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_SMART_BRAND_COLORS} brand colors are supported",
        )
    return normalized or None


_DEFAULT_EAND_PANEL_COLOR = ("#E00600", "e& red")
_DEFAULT_EAND_ACCENT_COLOR = ("#0B1F3A", "dark blue")
_MAX_SUPPORTING_BRAND_COLORS = 2


def _brand_palette_roles(
    custom_colors: list[str] | None,
) -> tuple[tuple[str, str], tuple[str, str], list[str]]:
    """Resolve (panel_color, accent_color, supporting_colors) for the prompt.
    Panel = the dominant color for large panels/section bands/headlines.
    Accent = the sparing color for small emphasis (numbers, rules, markers).
    Falls back to the default e& palette when no usable custom colors were
    extracted from an uploaded reference deck."""
    if not custom_colors:
        return _DEFAULT_EAND_PANEL_COLOR, _DEFAULT_EAND_ACCENT_COLOR, []

    panel = (custom_colors[0], custom_colors[0])
    accent = (
        (custom_colors[1], custom_colors[1])
        if len(custom_colors) > 1
        else _DEFAULT_EAND_ACCENT_COLOR
    )
    supporting = custom_colors[2 : 2 + _MAX_SUPPORTING_BRAND_COLORS]
    return panel, accent, supporting


def get_smart_brand_prompt(
    template_id: str | None, custom_colors: list[str] | None = None
) -> str:
    """Return the small layout contract given to the model, never the source HTML.

    `custom_colors` are hex colors extracted from a user-uploaded reference
    deck (see templates/pptx_color_extraction.py), ranked by how prominently
    they're actually used in that deck. When present they replace the
    default e& red/dark-blue palette; the fixed brand chrome (logo,
    Confidential label, footer bar) and layout/footer rules are unaffected —
    only the model's own content colors change."""
    if template_id is None:
        return ""
    if template_id != EAND_SMART_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="Unknown Smart brand template")

    (panel_hex, panel_name), (accent_hex, accent_name), supporting_colors = (
        _brand_palette_roles(custom_colors)
    )
    supporting_line = (
        f"\n- Supporting palette colors, for chart series or minor variety only: "
        f"{', '.join(supporting_colors)}."
        if supporting_colors
        else ""
    )
    source_note = (
        "This palette was extracted from the user's uploaded reference deck; "
        "treat it as the brand's real colors, not a suggestion."
        if custom_colors
        else "This is the default e& corporate palette."
    )

    return f"""

e& BRAND TEMPLATE CONTRACT
This presentation is rendered on a fixed e& corporate page shell after you
respond. Do not create, mention, or modify its logo, Confidential label, or
coloured footer bar. Use a white slide background.

FIXED DECK BOOKENDS (strict)
The e& workflow creates the branded title slide and final thank-you slide
outside your response. Return content slides only: never emit a
`data-slide-type="title"` or `data-slide-type="closing"` section. If the
user's requested outline begins with "Slide 1 — Title", treat that material as
the topic/context for the first content slide after the fixed title. Likewise,
do not create a separate closing or thank-you slide. The requested total slide
count already reserves these two fixed e& slides.

COLOUR PALETTE (required)
{source_note}
- Use {panel_hex} for large panels, section bands, headlines, and secondary emphasis.
- Use {accent_hex} sparingly for primary emphasis, key numbers, rules, and calls to action.
- Use white #FFFFFF as the primary canvas and card background, and black #000000
  for body copy and fine detail.{supporting_line}
- Keep the deck visually restrained: do not introduce colours outside this
  palette (plus white/black). When a lighter surface is needed, use white
  with a black or {panel_hex} border rather than a new tinted colour.
- Use {accent_hex} sparingly against white or {panel_hex} for high-contrast
  emphasis; never use {accent_hex} for long paragraphs of body text.

Generate only the main content layer. Keep all meaningful content within x=64
to x=1216 and y=48 to y=630. The area from y=640 to y=720 is reserved for the
fixed e& footer and must remain empty. Do not add a footer, page number, logo,
or other content in that reserved area. Use clean executive layouts and
restrained colour accents from this palette.

CONTENT DESIGN DIRECTION (required)
- Avoid generic document-like bullet lists. Turn grouped ideas into a clear
  executive composition: a numbered sequence, a 2–4 card grid, a comparison,
  a process, or a strong single-statement layout, selected to fit the content.
- Use generous white space, {panel_hex} section bands or side rails, thin
  {panel_hex}/#D9DEE7 rules, and {accent_hex} highlights. Cards should be white,
  flat or very subtly shadowed, with square-to-softly-rounded corners.
- A full-height {panel_hex} side rail (e.g. matching the height of a card grid
  next to it) is a frequent source of overflow: its checklist items stack
  vertically with nothing to shrink them, so it silently overflows past the
  bottom of the slide instead of visibly colliding with anything. Cap it at
  3-4 items with a short, single-line description each; do not give it more
  items or longer descriptions than that.
- For checklist content, use compact {accent_hex} circular check markers with a white
  check, or a thin {accent_hex} vertical rule; never use colours outside this palette.
- Keep typography editorial and high contrast: a concise {panel_hex} headline,
  black supporting copy, and {accent_hex} only for labels, key figures, and markers.
- Vary the layout from slide to slide while retaining this same {panel_name},
  {accent_name}, white, and black visual language.
""".strip()


def apply_smart_brand_template(template_id: str | None, slide_html: str) -> str:
    """Place fixed brand chrome above one validated Smart slide HTML fragment."""
    if template_id is None:
        return slide_html
    if template_id != EAND_SMART_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="Unknown Smart brand template")
    if "data-brand-template-element=\"eand-logo\"" in slide_html:
        return slide_html
    if _SECTION_CLOSE_RE.search(slide_html) is None:
        raise HTTPException(status_code=400, detail="Invalid Smart slide for brand template")
    return _SECTION_CLOSE_RE.sub(f"\n{_EAND_FOOTER_HTML}\n</section>", slide_html)
