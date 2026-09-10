import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

async function importTableExportCapture() {
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "table-export-capture-"));
  const outfile = path.join(tempDirectory, "table-export-capture.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["lib/table-export-capture.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

// A minimal fake <td>/<tr> shape: resolveTableGrid only ever reads
// `tr.cells` (array-like) and `td.rowSpan`/`td.colSpan`, so a plain array of
// plain objects stands in for the real DOM without needing jsdom.
function fakeRow(cells) {
  return { cells };
}

function fakeCell(rowSpan = 1, colSpan = 1, extra = {}) {
  return { rowSpan, colSpan, ...extra };
}

test("resolveTableGrid assigns sequential anchors for a plain grid with no spans", async () => {
  const { resolveTableGrid } = await importTableExportCapture();

  const rows = [
    fakeRow([fakeCell(1, 1, { id: "r0c0" }), fakeCell(1, 1, { id: "r0c1" })]),
    fakeRow([fakeCell(1, 1, { id: "r1c0" }), fakeCell(1, 1, { id: "r1c1" })]),
  ];

  const resolved = resolveTableGrid(rows);

  assert.deepEqual(
    resolved.map((cell) => [cell.rowIndex, cell.colIndex, cell.td.id]),
    [
      [0, 0, "r0c0"],
      [0, 1, "r0c1"],
      [1, 0, "r1c0"],
      [1, 1, "r1c1"],
    ],
  );
});

test("resolveTableGrid skips columns consumed by an earlier cell's colspan in the same row", async () => {
  const { resolveTableGrid } = await importTableExportCapture();

  const rows = [
    fakeRow([
      fakeCell(1, 2, { id: "wide" }), // occupies col 0 and col 1
      fakeCell(1, 1, { id: "after-wide" }), // must land at col 2, not col 1
    ]),
  ];

  const resolved = resolveTableGrid(rows);

  assert.deepEqual(
    resolved.map((cell) => [cell.rowIndex, cell.colIndex, cell.colSpan, cell.td.id]),
    [
      [0, 0, 2, "wide"],
      [0, 2, 1, "after-wide"],
    ],
  );
});

test("resolveTableGrid skips a column occupied by a rowspan from the row above", async () => {
  const { resolveTableGrid } = await importTableExportCapture();

  const rows = [
    fakeRow([
      fakeCell(2, 1, { id: "tall" }), // occupies (0,0) and (1,0)
      fakeCell(1, 1, { id: "r0c1" }),
    ]),
    fakeRow([
      // (1,0) is occupied by "tall" -> this cell must resolve to (1,1)
      fakeCell(1, 1, { id: "r1c1" }),
    ]),
  ];

  const resolved = resolveTableGrid(rows);

  assert.deepEqual(
    resolved.map((cell) => [cell.rowIndex, cell.colIndex, cell.td.id]),
    [
      [0, 0, "tall"],
      [0, 1, "r0c1"],
      [1, 1, "r1c1"],
    ],
  );
});

test("resolveTableGrid handles a combined colspan+rowspan cell", async () => {
  const { resolveTableGrid } = await importTableExportCapture();

  const rows = [
    fakeRow([
      fakeCell(2, 2, { id: "block" }), // occupies (0,0)-(1,1)
      fakeCell(1, 1, { id: "r0c2" }),
    ]),
    fakeRow([
      // (1,0) and (1,1) occupied by "block" -> lands at (1,2)
      fakeCell(1, 1, { id: "r1c2" }),
    ]),
  ];

  const resolved = resolveTableGrid(rows);

  assert.deepEqual(
    resolved.map((cell) => [cell.rowIndex, cell.colIndex, cell.rowSpan, cell.colSpan, cell.td.id]),
    [
      [0, 0, 2, 2, "block"],
      [0, 2, 1, 1, "r0c2"],
      [1, 2, 1, 1, "r1c2"],
    ],
  );
});

function fakeResolvedCell(rowIndex, colIndex, colSpan, width) {
  return {
    rowIndex,
    colIndex,
    rowSpan: 1,
    colSpan,
    td: { getBoundingClientRect: () => ({ width }) },
  };
}

test("computeColumnWidthsPx reads widths from a fully unspanned row", async () => {
  const { computeColumnWidthsPx } = await importTableExportCapture();

  const resolvedCells = [
    fakeResolvedCell(0, 0, 1, 100),
    fakeResolvedCell(0, 1, 1, 200),
    fakeResolvedCell(1, 0, 1, 999), // a later row's widths must not be used
    fakeResolvedCell(1, 1, 1, 999),
  ];

  const widths = computeColumnWidthsPx(resolvedCells, 2);
  assert.deepEqual(widths, [100, 200]);
});

test("computeColumnWidthsPx falls back to null when every row has a colspan", async () => {
  const { computeColumnWidthsPx } = await importTableExportCapture();

  const resolvedCells = [
    fakeResolvedCell(0, 0, 2, 300), // colspan=2, so this row can't be used
    fakeResolvedCell(1, 0, 2, 300),
  ];

  const widths = computeColumnWidthsPx(resolvedCells, 2);
  assert.equal(widths, null);
});

test("computeColumnWidthsPx falls back to null when no row's cell count matches the column count", async () => {
  const { computeColumnWidthsPx } = await importTableExportCapture();

  // Only 1 cell reported for a 2-column table (e.g. a merged/short row).
  const resolvedCells = [fakeResolvedCell(0, 0, 1, 100)];

  const widths = computeColumnWidthsPx(resolvedCells, 2);
  assert.equal(widths, null);
});
