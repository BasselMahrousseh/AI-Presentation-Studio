import pytest
from pydantic import ValidationError

from constants.presentation import MAX_NUMBER_OF_SLIDES, MAX_OUTLINE_CONTENT_WORDS
from models.presentation_outline_model import PresentationOutlineModel, SlideOutlineModel
from utils.outline_limits import count_outline_words, trim_text_to_word_limit
from utils.outline_utils import (
    _extract_outline_title,
    detect_explicit_slide_count,
    get_images_for_slides_from_outline,
    get_no_of_toc_required_for_n_outlines,
    get_presentation_outline_model_with_toc,
    get_presentation_title_from_presentation_outline,
)


def test_get_presentation_title_handles_prefixed_page_heading():
    outline = PresentationOutlineModel(
        slides=[SlideOutlineModel(content="## Page 1: Growth/Plan\\Roadmap\nBody")]
    )

    title = get_presentation_title_from_presentation_outline(outline)
    assert title == "GrowthPlanRoadmap Body"


def test_get_presentation_title_for_empty_outline():
    outline = PresentationOutlineModel(slides=[])
    assert get_presentation_title_from_presentation_outline(outline) == "Untitled Presentation"


def test_slide_outline_content_is_trimmed_to_word_limit():
    assert MAX_OUTLINE_CONTENT_WORDS == 300
    content = " ".join(
        f"word{i}" for i in range(MAX_OUTLINE_CONTENT_WORDS + 3)
    )

    slide = SlideOutlineModel(content=content)

    assert count_outline_words(slide.content) == MAX_OUTLINE_CONTENT_WORDS
    assert f"word{MAX_OUTLINE_CONTENT_WORDS - 1}" in slide.content
    assert f"word{MAX_OUTLINE_CONTENT_WORDS}" not in slide.content


def test_trim_text_to_word_limit_excludes_a_half_written_table_row():
    # Each markdown table row is its own line; a naive word-count cutoff
    # would land inside row 3 (since "|" counts as its own word), leaving a
    # row with only its first cell. The line-safe trim must drop that whole
    # partial row instead of emitting a mangled one.
    header = "| Priority | Model | Role |"
    separator = "|---|---|---|"
    row1 = "| 1 | GPT-OSS-120B | Core reasoning |"
    row2 = "| 2 | Qwen3-VL-235B | Documents |"
    row3 = "| 3 | Qwen3.5-397B | Premium generalist |"
    content = "\n".join([header, separator, row1, row2, row3])

    # "|" counts as its own word under \S+, so: header=7, separator=1,
    # row1=8, row2=7 -> 23 words before row3; row3 itself is 8 words. A
    # limit of 26 lands 3 words into row3 under the old word-count-only
    # cutoff (mid-row, right after "| 3 |").
    trimmed = trim_text_to_word_limit(content, max_words=26)

    assert row1 in trimmed
    assert row2 in trimmed
    assert row3 not in trimmed
    assert "| 3 |" not in trimmed


def test_trim_text_to_word_limit_falls_back_to_word_cutoff_for_a_single_long_line():
    content = " ".join(f"word{i}" for i in range(10))

    trimmed = trim_text_to_word_limit(content, max_words=5)

    assert trimmed == "word0 word1 word2 word3 word4"


def test_trim_text_to_word_limit_keeps_text_under_the_limit_unchanged():
    content = "## Title\nSome short body text."

    assert trim_text_to_word_limit(content, max_words=300) == content


def test_detect_explicit_slide_count_finds_clean_ascending_run():
    content = (
        "Slide 1 — Why the Earlier Shortlist Excluded Some Frontier Models\n"
        "Main message\n"
        "Slide 2 — Absolute Best Frontier Open Models by Category\n"
        "General Chat & Reasoning\n"
        "Slide 3 — Best Models for 8x Gaudi 3 Deployment\n"
        "Priority table\n"
        "Slide 4 — Recommended Rollout and Evaluation Backlog\n"
        "Phase 1\n"
    )

    assert detect_explicit_slide_count(content) == 4


def test_detect_explicit_slide_count_accepts_common_separators_and_case():
    content = (
        "slide 1: Intro\n"
        "SLIDE 2 - Middle\n"
        "Slide 3. End\n"
    )

    assert detect_explicit_slide_count(content) == 3


def test_detect_explicit_slide_count_requires_at_least_two_markers():
    assert detect_explicit_slide_count("Slide 1 — Only one marker here") is None


def test_detect_explicit_slide_count_rejects_gapped_numbering():
    content = "Slide 1 — Intro\nSlide 3 — Jumps ahead\n"

    assert detect_explicit_slide_count(content) is None


def test_detect_explicit_slide_count_rejects_incidental_out_of_order_mentions():
    content = (
        "As shown in slide 5 of last quarter's deck, growth continued.\n"
        "We revisited slide 12 during the review.\n"
    )

    assert detect_explicit_slide_count(content) is None


def test_detect_explicit_slide_count_handles_empty_content():
    assert detect_explicit_slide_count("") is None
    assert detect_explicit_slide_count(None) is None


def test_presentation_outline_rejects_more_than_max_slides():
    with pytest.raises(ValidationError):
        PresentationOutlineModel(
            slides=[
                SlideOutlineModel(content=f"## Slide {index}")
                for index in range(MAX_NUMBER_OF_SLIDES + 1)
            ]
        )


@pytest.mark.parametrize(
    ("n_outlines", "title_slide", "target_total_slides", "expected"),
    [
        (0, True, None, 0),
        (12, True, None, 2),
        (12, False, None, 2),
        (8, True, 25, 3),
    ],
)
def test_calculate_no_of_toc_required_for_n_outlines(
    n_outlines: int,
    title_slide: bool,
    target_total_slides: int | None,
    expected: int,
):
    assert (
        get_no_of_toc_required_for_n_outlines(
            n_outlines=n_outlines,
            title_slide=title_slide,
            target_total_slides=target_total_slides,
        )
        == expected
    )


def test_get_presentation_outline_model_with_toc_inserts_expected_slide_structure():
    outline = PresentationOutlineModel(
        slides=[
            SlideOutlineModel(content="## Title slide"),
            SlideOutlineModel(content="## Market Overview"),
            SlideOutlineModel(content="## Product Strategy"),
        ]
    )

    with_toc = get_presentation_outline_model_with_toc(
        outline=outline,
        n_toc_slides=1,
        title_slide=True,
    )

    assert len(with_toc.slides) == 4
    toc_content = with_toc.slides[1].content
    assert toc_content.startswith("## Table of Contents")
    assert "Page number: 3, Title: Market Overview" in toc_content
    assert "Page number: 4, Title: Product Strategy" in toc_content


def test_extract_outline_title_uses_heading_then_sentence_then_fallback():
    assert _extract_outline_title("## Heading title\nBody") == "Heading title"
    assert _extract_outline_title("First sentence. Second sentence.") == "First sentence."
    assert _extract_outline_title(" \nline fallback\n") == "line fallback"
    assert _extract_outline_title("") == "Slide"


def test_get_images_for_slides_from_outline_deduplicates_and_filters():
    slides = [
        SlideOutlineModel(
            content=(
                "Image https://cdn.example.com/a.png and duplicate "
                "https://cdn.example.com/a.png and invalid https://example.com/nope.txt"
            )
        ),
        SlideOutlineModel(content="No URL here"),
    ]

    extracted = get_images_for_slides_from_outline(slides)

    assert extracted[0] == ["https://cdn.example.com/a.png"]
    assert extracted[1] == []
