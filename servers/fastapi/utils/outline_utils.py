import math
import re
from typing import Optional

from constants.presentation import MAX_NUMBER_OF_SLIDES

from models.presentation_outline_model import (
    PresentationOutlineModel,
)


HEADING_PATTERN = re.compile(r"^\s{0,3}#+\s*(.+)$", re.MULTILINE)
FIRST_SENTENCE_PATTERN = re.compile(r"^\s*([^.?!]+?[.?!])", re.DOTALL)
IMAGE_URL_PATTERN = re.compile(
    r"https?://[-\w./%~:!$&'()*+,;=]+?\.(?:jpe?g|png|webp)(?:\?[^\s\"\'\\]*)?",
    re.IGNORECASE | re.UNICODE,
)
EXPLICIT_SLIDE_MARKER_PATTERN = re.compile(
    r"(?im)^\s*slide\s+(\d{1,3})\s*[-–—:.)]"
)


def detect_explicit_slide_count(content: Optional[str]) -> Optional[int]:
    """Detect content that already declares its own slide boundaries via
    repeated 'Slide N -' style headers - a common pattern when a user pastes
    a pre-structured planning document rather than a loose topic brief.

    Returns the number of distinct content slides declared, or None if the
    content doesn't show this pattern confidently enough to override the
    normal auto-detect slide count. Requires a clean ascending run starting
    at 1 (e.g. 1, 2, 3, 4) so an incidental aside like "as shown in slide 5
    of last quarter's deck" elsewhere in the text doesn't misfire this.
    """
    if not content:
        return None

    matches = EXPLICIT_SLIDE_MARKER_PATTERN.findall(content)
    if len(matches) < 2:
        return None

    numbers = sorted({int(match) for match in matches})
    if numbers != list(range(1, len(numbers) + 1)):
        return None

    return len(numbers)


def get_presentation_title_from_presentation_outline(
    presentation_outline: PresentationOutlineModel,
) -> str:
    if not presentation_outline.slides:
        return "Untitled Presentation"

    first_content = presentation_outline.slides[0].content or ""

    if re.match(r"^\s*#{1,6}\s*Page\s+\d+\b", first_content):
        first_content = re.sub(
            r"^\s*#{1,6}\s*Page\s+\d+\b[\s,:\-]*",
            "",
            first_content,
            count=1,
        )

    return (
        first_content[:100]
        .replace("#", "")
        .replace("/", "")
        .replace("\\", "")
        .replace("\n", " ")
    )


def get_no_of_outlines_to_generate_for_n_slides(
    *,
    n_slides: int,
    toc: bool,
    title_slide: bool,
) -> int:
    # Decks stored before the limit dropped can still carry a larger count;
    # asking for more than the parser keeps would fail the count check.
    n_slides = min(n_slides, MAX_NUMBER_OF_SLIDES)
    if toc:
        n_toc_1 = math.ceil(((n_slides - 1) if title_slide else n_slides) / 10)
        n_toc_2 = math.ceil((n_slides - n_toc_1) / 10)

        return n_slides - n_toc_2

    else:
        return n_slides


