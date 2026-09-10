/**
 * Captures live, fully-laid-out <table> geometry/content on the export-only
 * (/pdf-maker) render path, and reports it to FastAPI so a post-export pass
 * (pptx_native_table_service.py) can swap the flattened table images the
 * export pipeline always produces (the closed-source converter forces any
 * real <table> tag into one screenshot, the same treatment <canvas>/<svg>
 * get) for real, editable native PowerPoint tables.
 *
 * Mirrors chart-export-capture.ts's structure and every hard-won lesson in
 * it: pure functions kept separate from DOM-touching orchestration (for
 * unit-testability via the esbuild-based node:test harness), a settle-wait
 * before reading geometry (see waitForStableTableLayout's docstring for the
 * font-reflow trap that motivates it), and navigator.sendBeacon instead of
 * fetch/XHR (see the hard constraint at the bottom of this file).
 *
 * Best-effort throughout: any failure here must never affect the export
 * itself, so every entry point below only ever logs and returns/skips.
 */

export type CapturedTableCell = {
  rowIndex: number;
  colIndex: number;
  rowSpan: number;
  colSpan: number;
  text: string;
  isHeaderCell: boolean;
  backgroundColor: string | null;
  textColor: string | null;
  fontFamily: string | null;
  fontSize: number | null;
  fontWeight: string | number | null;
  textAlign: "left" | "center" | "right" | "justify" | null;
  bottomBorderColor: string | null;
  bottomBorderWidthPx: number | null;
};

export type CapturedTable = {
  slideOrderIndex: number;
  boundingBox: { left: number; top: number; width: number; height: number };
  rowCount: number;
  colCount: number;
  columnWidthsPx: number[] | null;
  rowHeightsPx: number[];
  cells: CapturedTableCell[];
};

// Only real <table> elements inside a slide's own content are ever
// candidates - this selector is already fully scoped to Smart-mode content:
// the only two other <table> usages in the whole frontend (MiniDataTable and
// an unused components/ui/table.tsx primitive) never render on this page.
// Div-based "fake tables" and TemplateV2's own grid-based `table` element
// never match a real <table> tag, so they're excluded automatically - no
// special-case code needed.
const TABLE_SELECTOR = ".main-slide table";

const LAYOUT_SETTLE_POLL_MS = 100;
const LAYOUT_SETTLE_TIMEOUT_MS = 5000;
const LAYOUT_SETTLE_EPSILON_PX = 0.5;
const LAYOUT_SETTLE_STABLE_ROUNDS = 8;

type ResolvedCell = {
  rowIndex: number;
  colIndex: number;
  rowSpan: number;
  colSpan: number;
  td: HTMLTableCellElement;
};

/**
 * The standard HTML table grid-resolution algorithm: walk DOM rows
 * top-to-bottom, tracking which (row, col) positions earlier rows' rowSpans
 * already occupy, and assign each real DOM cell its true grid anchor
 * (skipping occupied columns as it scans left to right). A spanned-over
 * position never appears as a separate DOM cell, so the resulting list
 * already has exactly one entry per merge region (the anchor) - giving every
 * captured cell grid coordinates that match python-pptx's own
 * `table.cell(row, col)` addressing.
 */
export function resolveTableGrid(
  domRows: HTMLTableRowElement[],
): ResolvedCell[] {
  const resolved: ResolvedCell[] = [];
  // occupied[row] is a Set of column indices already claimed by an earlier
  // row's rowSpan (or by an earlier cell in the same row).
  const occupied: Map<number, Set<number>> = new Map();
  const occupiedCols = (row: number): Set<number> => {
    let set = occupied.get(row);
    if (!set) {
      set = new Set();
      occupied.set(row, set);
    }
    return set;
  };

  domRows.forEach((tr, rowIndex) => {
    let col = 0;
    const cols = occupiedCols(rowIndex);
    Array.from(tr.cells).forEach((td) => {
      while (cols.has(col)) col += 1;

      const rowSpan = Math.max(1, td.rowSpan || 1);
      const colSpan = Math.max(1, td.colSpan || 1);

      resolved.push({ rowIndex, colIndex: col, rowSpan, colSpan, td });

      for (let r = rowIndex; r < rowIndex + rowSpan; r += 1) {
        const rowOccupied = occupiedCols(r);
        for (let c = col; c < col + colSpan; c += 1) {
          rowOccupied.add(c);
        }
      }
      col += colSpan;
    });
  });

  return resolved;
}

const _TEXT_ALIGN_VALUES: ReadonlySet<string> = new Set([
  "left",
  "center",
  "right",
  "justify",
]);

function normalizeTextAlign(
  value: string,
): "left" | "center" | "right" | "justify" | null {
  const normalized = value.trim().toLowerCase();
  if (normalized === "start") return "left";
  if (normalized === "end") return "right";
  return _TEXT_ALIGN_VALUES.has(normalized)
    ? (normalized as "left" | "center" | "right" | "justify")
    : null;
}

function isRealColor(value: string | undefined | null): value is string {
  if (!value) return false;
  const trimmed = value.trim();
  return (
    trimmed.length > 0 &&
    trimmed !== "transparent" &&
    trimmed !== "rgba(0, 0, 0, 0)"
  );
}

/**
 * Reads a cell's visual style from getComputedStyle, except: if the cell has
 * exactly one child element whose textContent equals the cell's own full
 * textContent (the "status badge" pattern - a colored <span> filling an
 * otherwise-plain <td>, used in this app's "Status table"/"Financial table"
 * slide patterns), read background/text color from that child instead.
 * Scoped narrowly on purpose - a known limitation, not general nested-element
 * modeling (see the table-export plan's documented V1 limitations).
 */
export function detectCellVisualStyle(td: HTMLTableCellElement): {
  backgroundColor: string | null;
  textColor: string | null;
  fontFamily: string | null;
  fontSize: number | null;
  fontWeight: string | number | null;
} {
  let styleSource: Element = td;
  const cellText = (td.textContent ?? "").trim();
  const childElements = Array.from(td.children);
  if (
    childElements.length === 1 &&
    (childElements[0].textContent ?? "").trim() === cellText &&
    cellText.length > 0
  ) {
    styleSource = childElements[0];
  }

  const computed = getComputedStyle(styleSource);
  const fontSizePx = parseFloat(computed.fontSize);

  return {
    backgroundColor: effectiveCellBackgroundColor(styleSource, td),
    textColor: isRealColor(computed.color) ? computed.color : null,
    fontFamily: computed.fontFamily || null,
    fontSize: Number.isFinite(fontSizePx) ? fontSizePx : null,
    fontWeight: computed.fontWeight || null,
  };
}

/**
 * A cell's own background is what a naive getComputedStyle(td) read would
 * miss for a very common real pattern: this app's generation prompt (and
 * plain Tailwind authoring in general) colors a table's header by putting
 * the background class on the <tr> itself (`<tr class="bg-[#0B1F3A]">`),
 * not repeated on every <th>. CSS background-color does not inherit to
 * children (unlike `color`, which getComputedStyle already resolves through
 * inheritance on its own) - a child with no explicit background of its own
 * computes to fully transparent, even though the parent's color visibly
 * paints through it. Confirmed against a real reported bug: a native
 * exported table's header rendered as PowerPoint's generic default blue
 * instead of the deck's real dark navy, because the captured backgroundColor
 * for every header cell was silently null.
 *
 * Walks from the cell (or its single-child style source) up through its
 * ancestors - <tr>, <thead>/<tbody>, <table>, and (deliberately, see below)
 * past the table into whatever card/wrapper divs sit between it and the
 * slide's own root <section> - stopping at the first real (non-transparent)
 * background found.
 *
 * An earlier version of this stopped at the <table> boundary, on the theory
 * that reaching further out risked pulling in an unrelated ancestor's color.
 * That was wrong, confirmed by a second real user report on the same table:
 * a plain white table body (no per-row color of its own, correctly captured
 * as null) still rendered with a visible grayish-blue tint in the exported
 * file, because python-pptx's default table style bakes its own tinted
 * "whole table" fill into every un-colored cell - `table.horz_banding =
 * False` only ever controlled the *alternating* accent band, not that base
 * fill. There is no meaningful difference between "this cell's color comes
 * from its <table>'s own background" and "...from the slide's root
 * <section> two divs further up" - both are just the real, single value a
 * browser resolves for that cell, and capturing whichever one is real is
 * what makes the native table's explicit per-cell fill (which always wins
 * over the style's own default, see _apply_table_styling) match what the
 * app actually showed. Bounded at the slide's own root <section> (always
 * present on a Smart-mode slide, marked by `data-slide-type`) rather than
 * walking indefinitely, since anything above that boundary is the export
 * page's own wrapper chrome - never part of the slide's authored design.
 */
function effectiveCellBackgroundColor(
  styleSource: Element,
  td: HTMLTableCellElement,
): string | null {
  const own = getComputedStyle(styleSource).backgroundColor;
  if (isRealColor(own)) return own;

  // For the single-child "status badge" case, styleSource is that child, not
  // td itself - td's own background (if any, separate from the badge's) has
  // not been checked yet, so the walk starts there instead of skipping past
  // it straight to <tr>.
  let ancestor: Element | null = styleSource === td ? td.parentElement : td;
  while (ancestor) {
    const background = getComputedStyle(ancestor).backgroundColor;
    if (isRealColor(background)) return background;
    if (ancestor.hasAttribute("data-slide-type")) break;
    ancestor = ancestor.parentElement;
  }
  return null;
}

type BottomBorder = { color: string | null; widthPx: number | null };
const _NO_BOTTOM_BORDER: BottomBorder = { color: null, widthPx: null };

function ownBottomBorder(el: Element): BottomBorder | null {
  const computed = getComputedStyle(el);
  if (computed.borderBottomStyle === "none") return null;
  const widthPx = parseFloat(computed.borderBottomWidth);
  if (!Number.isFinite(widthPx) || widthPx <= 0) return null;
  const color = computed.borderBottomColor;
  if (!isRealColor(color)) return null;
  return { color, widthPx };
}

/**
 * Same reasoning and same ancestor-walk shape as effectiveCellBackgroundColor
 * (see its docstring for the full CSS-non-inheritance background): this
 * app's own generated tables put a row separator on the <tr> itself
 * (`<tr class="border-b border-black/15">`), not repeated on every <td>/<th>.
 * `border` is not an inherited CSS property either, so a plain
 * getComputedStyle(td) read would miss it exactly the same way backgroundColor
 * did. Bounded at the same `data-slide-type` slide-root boundary - a row
 * separator has no meaningful source further out than the slide itself.
 *
 * Deliberately bottom-border only: this app's own table-authoring pattern
 * (and the specific user report this was built for) only ever uses
 * `border-b` for row separators - top/left/right borders are not part of
 * that pattern, and capturing all four would multiply the OOXML-authoring
 * surface (see _apply_cell_bottom_border's docstring) for no observed need.
 */
function effectiveCellBottomBorder(
  styleSource: Element,
  td: HTMLTableCellElement,
): BottomBorder {
  const own = ownBottomBorder(styleSource);
  if (own) return own;

  let ancestor: Element | null = styleSource === td ? td.parentElement : td;
  while (ancestor) {
    const found = ownBottomBorder(ancestor);
    if (found) return found;
    if (ancestor.hasAttribute("data-slide-type")) break;
    ancestor = ancestor.parentElement;
  }
  return _NO_BOTTOM_BORDER;
}

/**
 * Finds a row where every cell has colSpan===1 and the cell count equals the
 * resolved column count - the only shape from which per-column widths can be
 * read unambiguously. Returns null (not a guess) when no such row exists,
 * letting the swap side fall back to add_table()'s equal-width default
 * rather than risk mismatched columns from a spanned row.
 */
export function computeColumnWidthsPx(
  resolvedCells: ResolvedCell[],
  colCount: number,
): number[] | null {
  const byRow = new Map<number, ResolvedCell[]>();
  resolvedCells.forEach((cell) => {
    const list = byRow.get(cell.rowIndex) ?? [];
    list.push(cell);
    byRow.set(cell.rowIndex, list);
  });

  for (const cells of byRow.values()) {
    if (cells.length !== colCount) continue;
    if (!cells.every((cell) => cell.colSpan === 1)) continue;
    const sorted = [...cells].sort((a, b) => a.colIndex - b.colIndex);
    return sorted.map((cell) => cell.td.getBoundingClientRect().width);
  }
  return null;
}

export function readRowHeightsPx(table: HTMLTableElement): number[] {
  return Array.from(table.rows).map(
    (tr) => tr.getBoundingClientRect().height,
  );
}

type TableRect = { left: number; top: number; width: number; height: number };

function rectOf(el: Element): TableRect {
  const rect = el.getBoundingClientRect();
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

function readAllTrackedRects(tables: HTMLTableElement[]): TableRect[] {
  const rects: TableRect[] = [];
  tables.forEach((table) => {
    rects.push(rectOf(table));
    // Column geometry is derived from *cell* rects, not just the table's
    // outer rect, so the settle-wait must also cover the header/first-data
    // row's cells - the outer table rect can look perfectly still while its
    // internal column widths are still shifting.
    const firstRow = table.rows[0];
    if (firstRow) {
      Array.from(firstRow.cells).forEach((td) => rects.push(rectOf(td)));
    }
  });
  return rects;
}

function rectsAreStable(before: TableRect[], after: TableRect[]): boolean {
  if (before.length !== after.length) return false;
  return before.every((rect, index) => {
    const next = after[index];
    return (
      Math.abs(rect.left - next.left) <= LAYOUT_SETTLE_EPSILON_PX &&
      Math.abs(rect.top - next.top) <= LAYOUT_SETTLE_EPSILON_PX &&
      Math.abs(rect.width - next.width) <= LAYOUT_SETTLE_EPSILON_PX &&
      Math.abs(rect.height - next.height) <= LAYOUT_SETTLE_EPSILON_PX
    );
  });
}

function safeRead<T>(read: () => T): T | undefined {
  try {
    return read();
  } catch {
    return undefined;
  }
}

/**
 * Blocks until every tracked table's on-page geometry has held still across
 * several consecutive polls, mirroring waitForStableChartLayout's same
 * reasoning: a chart/table that reports "rendered" is not the same as the
 * page having finished laying out, and a second wave of font loading
 * (`document.fonts.status`) reflows content above/around a table well after
 * it first appears settled. Bounded by a timeout that fails open - a
 * slightly-off box that fails the backend's IoU check is no worse than
 * today's flattened image, whereas waiting forever would lose the capture
 * entirely. Deliberately uses only timers and layout reads: no fetch/XHR,
 * which would risk stalling the export's own `waitUntil: "networkidle0"`
 * navigation (see the hard constraint at the bottom of this file).
 */
async function waitForStableTableLayout(
  tables: HTMLTableElement[],
): Promise<void> {
  if (!tables.length) return;
  const start = Date.now();
  let previous = readAllTrackedRects(tables);
  let stableRounds = 0;

  while (Date.now() - start <= LAYOUT_SETTLE_TIMEOUT_MS) {
    await new Promise((resolve) => setTimeout(resolve, LAYOUT_SETTLE_POLL_MS));

    const current = readAllTrackedRects(tables);
    const fontsBusy = safeRead(() => document.fonts?.status) === "loading";
    stableRounds =
      !fontsBusy && rectsAreStable(previous, current) ? stableRounds + 1 : 0;
    previous = current;

    if (stableRounds >= LAYOUT_SETTLE_STABLE_ROUNDS) return;
  }
}

function captureOneTable(
  table: HTMLTableElement,
  slideOrderIndex: number,
  slideContainerEl: Element,
): CapturedTable | null {
  const domRows = Array.from(table.rows);
  if (!domRows.length) return null;

  const resolvedCells = resolveTableGrid(domRows);
  if (!resolvedCells.length) return null;

  const colCount = Math.max(
    ...resolvedCells.map((cell) => cell.colIndex + cell.colSpan),
  );
  const rowCount = domRows.length;

  const tableRect = table.getBoundingClientRect();
  const slideRect = slideContainerEl.getBoundingClientRect();
  const boundingBox = {
    left: tableRect.left - slideRect.left,
    top: tableRect.top - slideRect.top,
    width: tableRect.width,
    height: tableRect.height,
  };
  if (boundingBox.width <= 0 || boundingBox.height <= 0) return null;

  const cells: CapturedTableCell[] = resolvedCells.map((cell) => {
    const style = detectCellVisualStyle(cell.td);
    const textAlign = normalizeTextAlign(getComputedStyle(cell.td).textAlign);
    // Not routed through the single-child "status badge" style source: a
    // badge is a per-cell content pill, never the source of a row separator
    // border, so the walk always starts from the real <td>/<th> itself.
    const bottomBorder = effectiveCellBottomBorder(cell.td, cell.td);
    return {
      rowIndex: cell.rowIndex,
      colIndex: cell.colIndex,
      rowSpan: cell.rowSpan,
      colSpan: cell.colSpan,
      text: (cell.td.textContent ?? "").trim(),
      isHeaderCell: cell.td.tagName === "TH",
      backgroundColor: style.backgroundColor,
      textColor: style.textColor,
      fontFamily: style.fontFamily,
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
      textAlign,
      bottomBorderColor: bottomBorder.color,
      bottomBorderWidthPx: bottomBorder.widthPx,
    };
  });

  return {
    slideOrderIndex,
    boundingBox,
    rowCount,
    colCount,
    columnWidthsPx: computeColumnWidthsPx(resolvedCells, colCount),
    rowHeightsPx: readRowHeightsPx(table),
    cells,
  };
}

export async function captureAllTablesOnPage(opts: {
  token: string;
  presentationId: string;
  reportUrl: string;
}): Promise<void> {
  try {
    const tables = Array.from(
      document.querySelectorAll<HTMLTableElement>(TABLE_SELECTOR),
    );
    if (!tables.length) return;

    await waitForStableTableLayout(tables);

    const slideContainers = Array.from(
      document.querySelectorAll<HTMLElement>("#presentation-slides-wrapper .main-slide"),
    );

    const captured: CapturedTable[] = [];
    tables.forEach((table) => {
      // Isolated per table, mirroring chart-export-capture.ts's per-canvas
      // isolation fix - one malformed/unusual table must not blank the
      // whole capture and silently export every table in the deck as a
      // flattened image.
      try {
        const slideContainerEl = table.closest<HTMLElement>(".main-slide");
        if (!slideContainerEl) return;
        const slideOrderIndex = slideContainers.indexOf(slideContainerEl);
        if (slideOrderIndex < 0) return;

        const result = captureOneTable(table, slideOrderIndex, slideContainerEl);
        if (result) captured.push(result);
      } catch (error) {
        console.warn("[table-export-capture] Skipped one table", error);
      }
    });

    if (!captured.length) return;

    const payload = JSON.stringify({
      token: opts.token,
      presentation_id: opts.presentationId,
      tables: captured,
    });

    // Deliberately navigator.sendBeacon(), never fetch()/XHR: the export
    // tool navigates here with page.goto(url, {waitUntil: "networkidle0"}),
    // and ANY same-origin fetch()/XHR fired while that wait is still
    // pending - even one that completes quickly and successfully - was
    // empirically confirmed (see chart-export-capture.ts and CLAUDE.md) to
    // make Puppeteer's network-idle tracking never settle, hanging the whole
    // export until its 120s navigation timeout. /export/table-capture
    // doesn't require auth (best-effort endpoint), so sendBeacon's inability
    // to carry a custom cookie header isn't a functional loss.
    const sent =
      typeof navigator !== "undefined" && "sendBeacon" in navigator
        ? navigator.sendBeacon(
            opts.reportUrl,
            new Blob([payload], { type: "application/json" }),
          )
        : false;
    if (!sent) {
      await fetch(opts.reportUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
      }).catch(() => undefined);
    }
  } catch (error) {
    console.warn("[table-export-capture] Skipped native table capture", error);
  }
}
