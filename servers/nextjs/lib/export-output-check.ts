/**
 * Sanity checks on a finished export. The headless export can exit 0 and write a valid but EMPTY
 * file when it screenshots /pdf-maker before the page has hydrated its slides (seen on a cold
 * dev-mode compile). Nothing else notices, so the user downloads a 0-slide deck. These helpers let
 * the runner compare the output against how many slides the deck really has.
 */

const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_ENTRY_SIGNATURE = 0x02014b50;
const PPTX_SLIDE_ENTRY = /^ppt\/slides\/slide\d+\.xml$/;

/** Counts `ppt/slides/slideN.xml` entries by reading the zip central directory (no unzip needed). */
export function countPptxSlides(file: Buffer): number {
  let eocd = -1;
  for (let i = file.length - 22; i >= Math.max(0, file.length - 22 - 0xffff); i--) {
    if (file.readUInt32LE(i) === EOCD_SIGNATURE) {
      eocd = i;
      break;
    }
  }
  if (eocd === -1) throw new Error("Export output is not a valid PPTX (no zip directory).");

  const entryCount = file.readUInt16LE(eocd + 10);
  let offset = file.readUInt32LE(eocd + 16);
  let slides = 0;
  for (let i = 0; i < entryCount; i++) {
    if (offset + 46 > file.length || file.readUInt32LE(offset) !== CENTRAL_ENTRY_SIGNATURE) {
      throw new Error("Export output is not a valid PPTX (corrupt zip directory).");
    }
    const nameLength = file.readUInt16LE(offset + 28);
    const extraLength = file.readUInt16LE(offset + 30);
    const commentLength = file.readUInt16LE(offset + 32);
    const name = file.toString("utf8", offset + 46, offset + 46 + nameLength);
    if (PPTX_SLIDE_ENTRY.test(name)) slides++;
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return slides;
}

/**
 * Page count from the root `/Count` of the PDF page tree, or null when it cannot be read (for
 * example a PDF that keeps its page tree inside a compressed object stream). Null means "do not
 * judge", never "empty".
 */
export function countPdfPages(file: Buffer): number | null {
  const text = file.toString("latin1");
  let best: number | null = null;
  for (const match of text.matchAll(/\/Type\s*\/Pages\b[^>]*?\/Count\s+(\d+)|\/Count\s+(\d+)[^>]*?\/Type\s*\/Pages\b/g)) {
    const value = Number(match[1] ?? match[2]);
    if (best === null || value > best) best = value;
  }
  return best;
}

export type ExportCheck = { ok: true } | { ok: false; reason: string };

/** `expected` null/0 means the deck's size is unknown, so only a wholly empty output is rejected. */
export function checkExportOutput(
  format: "pptx" | "pdf",
  file: Buffer,
  expected: number | null
): ExportCheck {
  const actual = format === "pptx" ? countPptxSlides(file) : countPdfPages(file);
  if (actual === null) return { ok: true };
  if (actual === 0) {
    return { ok: false, reason: `the ${format.toUpperCase()} contains 0 slides` };
  }
  if (expected && actual < expected) {
    return { ok: false, reason: `the ${format.toUpperCase()} contains ${actual} of ${expected} slides` };
  }
  return { ok: true };
}
