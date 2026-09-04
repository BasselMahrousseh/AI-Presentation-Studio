import re
from typing import Any

from constants.presentation import MAX_OUTLINE_CONTENT_WORDS


OUTLINE_WORD_PATTERN = re.compile(r"\S+")


def count_outline_words(text: str) -> int:
    return len(OUTLINE_WORD_PATTERN.findall(text or ""))


def trim_text_to_word_limit(
    text: str,
    max_words: int = MAX_OUTLINE_CONTENT_WORDS,
) -> str:
    if max_words <= 0:
        return ""

    text = text or ""
    matches = list(OUTLINE_WORD_PATTERN.finditer(text))
    if len(matches) <= max_words:
        return text

    # Prefer cutting after the last whole line that still fits within the
    # word budget, so a markdown table row or list item is never left
    # half-written - a naive word-count cutoff can land mid-table-cell, since
    # "|" counts as its own word. Only falls back to a mid-line word cutoff
    # when a single line by itself already exceeds the whole budget - there
    # is nothing safe to back up to in that case.
    word_count = 0
    included_length = 0
    for line in text.splitlines(keepends=True):
        line_word_count = len(OUTLINE_WORD_PATTERN.findall(line))
        if word_count + line_word_count > max_words:
            break
        word_count += line_word_count
        included_length += len(line)

    if included_length > 0:
        return text[:included_length].rstrip()

    return text[: matches[max_words - 1].end()].rstrip()


def normalize_outline_content(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return trim_text_to_word_limit(value, MAX_OUTLINE_CONTENT_WORDS)


def normalize_outline_payload(payload: dict[str, Any], max_slides: int) -> dict[str, Any]:
    normalized = dict(payload)
    raw_slides = normalized.get("slides")
    if not isinstance(raw_slides, list):
        return normalized

    normalized["slides"] = [
        {
            **slide,
            "content": normalize_outline_content(slide.get("content", "")),
        }
        if isinstance(slide, dict)
        else {"content": normalize_outline_content(slide)}
        for slide in raw_slides[:max_slides]
    ]
    return normalized
