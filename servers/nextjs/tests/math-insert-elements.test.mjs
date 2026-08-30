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

async function importInsertElements() {
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "math-inserts-"));
  const outfile = path.join(tempDirectory, "insert-elements.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["components/slide-editor/insert/insert-elements.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

async function importTextRuns() {
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "latex-runs-"));
  const outfile = path.join(tempDirectory, "text-runs.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["components/slide-editor/text/text-runs.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

test("creates distinct editable LaTeX examples from the insert palette", async () => {
  const { createTextInsertElements } = await importInsertElements();
  const examples = {
    equation: String.raw`E = mc^2`,
    "equation-quadratic": String.raw`x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}`,
    "equation-summation": String.raw`\sum_{i=1}^{n} i = \frac{n(n+1)}{2}`,
    "equation-integral": String.raw`\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}`,
    "equation-matrix": String.raw`A = \begin{bmatrix} a & b \\ c & d \end{bmatrix}`,
  };

  for (const [id, latex] of Object.entries(examples)) {
    const [element] = createTextInsertElements(id);
    assert.equal(element.type, "text");
    assert.deepEqual(element.runs, [
      { type: "latex", latex, display_mode: true },
    ]);
    assert.equal(element.decorative, false);
  }
});

test("toggles a text selection between plain text and LaTeX", async () => {
  const { latexTextRunRangeAtCursor, toggleTextRunLatexForSelection } =
    await importTextRuns();
  const element = {
    type: "text",
    runs: [{ text: "Area = x^2" }],
  };
  const range = { start: 7, end: 10 };
  const withLatex = toggleTextRunLatexForSelection(element, range);

  assert.deepEqual(withLatex.runs, [
    { text: "Area = " },
    {
      type: "latex",
      latex: "x^2",
      display_mode: false,
      font: undefined,
    },
  ]);
  assert.deepEqual(latexTextRunRangeAtCursor(withLatex.runs, 8), range);

  const withText = toggleTextRunLatexForSelection(withLatex, range);
  assert.deepEqual(withText.runs, [{ text: "Area = x^2" }]);
});
