import pytest
from fastapi import HTTPException

from utils.smart_brand_templates import (
    EAND_TITLE_SUBTITLE,
    _tint_hex,
    apply_smart_brand_template,
    build_eand_thank_you_slide,
    build_eand_title_slide,
    get_smart_brand_prompt,
    normalize_smart_template_id,
)


def _smart_slide_html() -> str:
    return (
        '<section data-slide-type="content" data-slide-title="Strategy" '
        'class="relative h-[720px] w-[1280px] overflow-hidden">'
        '<div class="p-10">Content</div></section>'
    )


def test_eand_template_is_normalized_and_described_without_source_markup():
    assert normalize_smart_template_id(" EAND ") == "eand"

    prompt = get_smart_brand_prompt("eand")
    assert "fixed e& corporate page shell" in prompt
    assert "y=640 to y=720" in prompt
    assert "#E00600" in prompt
    assert "#0B1F3A" in prompt
    assert "#FFFFFF" in prompt
    assert "#000000" in prompt
    assert "eand-logo.png" not in prompt


def test_eand_shell_is_applied_once_and_keeps_the_generated_content():
    rendered = apply_smart_brand_template("eand", _smart_slide_html())

    assert '<div class="p-10">Content</div>' in rendered
    assert rendered.count('data-brand-template-element="eand-logo"') == 1
    assert rendered.count('data-brand-template-element="eand-footer-bar"') == 1
    assert "/smart-templates/eand/eand-logo.png" in rendered
    assert rendered.index('data-brand-template-element="eand-logo"') < rendered.rindex(
        "</section>"
    )
    assert apply_smart_brand_template("eand", rendered) == rendered


@pytest.mark.parametrize("value", ["other", "unknown-template"])
def test_unknown_brand_template_ids_are_rejected(value):
    with pytest.raises(HTTPException):
        normalize_smart_template_id(value)


def test_empty_brand_template_id_means_no_template():
    assert normalize_smart_template_id("") is None


def test_eand_fixed_title_and_thank_you_slides_use_the_supplied_assets():
    title_slide = build_eand_title_slide(
        "Board update & outlook", "A concise strategic overview"
    )
    thank_you_slide = build_eand_thank_you_slide()

    assert 'data-slide-type="title"' in title_slide
    assert "Board update &amp; outlook" in title_slide
    assert "/smart-templates/eand/eand-title-logo-white.png" in title_slide
    assert "/smart-templates/eand/eand-title-gradient.png" in title_slide
    assert 'data-slide-type="closing"' in thank_you_slide
    assert "/smart-templates/eand/eand-thank-you-background.png" in thank_you_slide
    assert "Thank you" in thank_you_slide


def test_eand_title_subtitle_is_a_safe_brand_label():
    title_slide = build_eand_title_slide(
        "Board update", EAND_TITLE_SUBTITLE
    )

    assert "e&amp; presentation" in title_slide
    assert "Generate a 12-slide strategy deck" not in title_slide


def test_tint_hex_blends_toward_white():
    assert _tint_hex("#E00600", 0.0) == "#E00600"
    assert _tint_hex("#E00600", 1.0) == "#FFFFFF"
    # A partial tint should land strictly between the base color and white
    # on every channel.
    tinted = _tint_hex("#0B1F3A", 0.5)
    base = (0x0B, 0x1F, 0x3A)
    tinted_rgb = tuple(int(tinted[i : i + 2], 16) for i in (1, 3, 5))
    assert all(base[i] < tinted_rgb[i] < 255 for i in range(3))


def test_default_eand_palette_gets_a_wider_chart_only_color_set():
    prompt = get_smart_brand_prompt("eand", None)

    assert "CHART COLOR PALETTE" in prompt
    # The base panel/accent colors, Etisalat's heritage green, and computed
    # tints must all be present as concrete hex values the model can use.
    assert "#82AA40" in prompt
    assert "#CCDB3B" in prompt
    assert _tint_hex("#E00600", 0.35) in prompt
    assert _tint_hex("#0B1F3A", 0.35) in prompt
    # Never offer white as a chart color - it disappears against the white
    # slide/card background, which is exactly the bug this fixes.
    chart_section = prompt[prompt.index("CHART COLOR PALETTE") :]
    palette_line = chart_section.split("may use this wider palette")[1].split("\n")[0]
    assert "#FFFFFF" not in palette_line
    assert "#FFF" not in palette_line


def test_custom_color_palette_does_not_get_the_synthetic_chart_palette():
    # An uploaded reference deck's extracted colors represent that deck's
    # real brand - don't invent additional (unbranded) colors on top of it.
    prompt = get_smart_brand_prompt("eand", ["#123456", "#654321", "#AABBCC"])

    assert "CHART COLOR PALETTE" not in prompt
    assert "#82AA40" not in prompt


