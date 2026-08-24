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


def get_eand_content_slide_count(total_slide_count: int) -> int:
    """Reserve the e& title and thank-you slides from the requested deck size."""
    content_slide_count = total_slide_count - EAND_FIXED_SLIDE_COUNT
    if content_slide_count < 1:
        raise HTTPException(
            status_code=400,
            detail="The e& template requires at least three slides",
        )
    return content_slide_count


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


def get_smart_brand_prompt(template_id: str | None) -> str:
    """Return the small layout contract given to the model, never the source HTML."""
    if template_id is None:
        return ""
    if template_id != EAND_SMART_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="Unknown Smart brand template")
    return """

e& BRAND TEMPLATE CONTRACT
This presentation is rendered on a fixed e& corporate page shell after you
respond. Do not create, mention, or modify its logo, Confidential label, or
coloured footer bar. Use a white slide background.

COLOUR PALETTE (required)
- Use e& red #E00600 for primary emphasis, key numbers, rules, and calls to action.
- Use dark blue #0B1F3A for large panels, section headers, and secondary emphasis.
- Use white #FFFFFF as the primary canvas and card background, and black #000000
  for body copy and fine detail.
- Keep the deck visually restrained: do not introduce other brand colours such as
  purple, green, orange, teal, or bright blue. When a lighter surface is needed,
  use white with a black or dark-blue border rather than a new tinted colour.
- Use red sparingly against white or dark blue for high-contrast emphasis; never
  use red for long paragraphs of body text.

Generate only the main content layer. Keep all meaningful content within x=64
to x=1216 and y=48 to y=630. The area from y=640 to y=720 is reserved for the
fixed e& footer and must remain empty. Do not add a footer, page number, logo,
or other content in that reserved area. Use clean executive layouts and
restrained e&-appropriate colour accents.
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
