export const MAX_NUMBER_OF_SLIDES = 50;
export const MAX_OUTLINE_CONTENT_WORDS = 300;

const WORD_PATTERN = /\S+/g;

export function countOutlineWords(value: string): number {
  return value.match(WORD_PATTERN)?.length ?? 0;
}

export function trimTextToWordLimit(
  value: string,
  maxWords = MAX_OUTLINE_CONTENT_WORDS
): string {
  if (maxWords <= 0) return "";

  const text = value || "";
  const matches = Array.from(text.matchAll(WORD_PATTERN));
  if (matches.length <= maxWords) return text;

  // Prefer cutting after the last whole line that still fits within the word
  // budget, so a markdown table row or list item is never left half-written
  // - a naive word-count cutoff can land mid-table-cell, since "|" counts as
  // its own word. Only falls back to a mid-line word cutoff when a single
  // line by itself already exceeds the whole budget - there is nothing safe
  // to back up to in that case.
  const lines = text.match(/[^\n]*\n?/g) ?? [];
  let wordCount = 0;
  let includedLength = 0;
  for (const line of lines) {
    if (line === "") continue;
    const lineWordCount = line.match(WORD_PATTERN)?.length ?? 0;
    if (wordCount + lineWordCount > maxWords) break;
    wordCount += lineWordCount;
    includedLength += line.length;
  }

  if (includedLength > 0) {
    return text.slice(0, includedLength).trimEnd();
  }

  const lastMatch = matches[maxWords - 1];
  const endIndex = (lastMatch.index ?? 0) + lastMatch[0].length;
  return text.slice(0, endIndex).trimEnd();
}

export function limitOutlines<T extends { content?: unknown }>(
  outlines: T[] | null | undefined
): { content: string }[] {
  if (!Array.isArray(outlines)) return [];

  return outlines.slice(0, MAX_NUMBER_OF_SLIDES).map((outline) => ({
    ...outline,
    content: trimTextToWordLimit(
      typeof outline?.content === "string"
        ? outline.content
        : String(outline?.content ?? "")
    ),
  }));
}

export function clampSlideCountValue(value: string): string {
  const digitsOnly = value.replace(/\D+/g, "");
  if (!digitsOnly) return "";

  const normalized = digitsOnly.replace(/^0+/, "");
  if (!normalized) return "";

  return String(Math.min(Number(normalized), MAX_NUMBER_OF_SLIDES));
}

export function parseLimitedSlideCount(
  value: string | null | undefined
): number | null {
  if (!value || !/^\d+$/.test(value)) return null;

  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;

  return Math.min(parsed, MAX_NUMBER_OF_SLIDES);
}
