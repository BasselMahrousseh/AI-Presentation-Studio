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

async function importSmartSlideArbitraryStyles() {
  const tempDirectory = await mkdtemp(
    path.join(os.tmpdir(), "smart-slide-arbitrary-styles-"),
  );
  const outfile = path.join(tempDirectory, "smart-slide-arbitrary-styles.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["lib/smart-slide-arbitrary-styles.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

/**
 * A minimal fake HTMLElement covering only what applyArbitraryTextStyles
 * actually touches: a real `.style` object to assert property writes
 * against, `getAttribute("class")`, and a `querySelectorAll("[class]")` that
 * recursively finds every descendant carrying a class attribute - the only
 * selector the function ever calls.
 */
function fakeElement({ className = "", children = [] } = {}) {
  const style = {};
  const element = {
    style,
    className,
    children,
    getAttribute(name) {
      if (name !== "class") return null;
      return className || null;
    },
    querySelectorAll() {
      const results = [];
      const walk = (nodes) => {
        for (const node of nodes) {
          if (node.getAttribute("class")) results.push(node);
          walk(node.children);
        }
      };
      walk(children);
      return results;
    },
  };
  return element;
}

test("text-[<px>] is applied as an inline font-size", async () => {
  const { applyArbitraryTextStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({ className: "text-[64px] font-bold" });

  applyArbitraryTextStyles(container);

  assert.equal(container.style.fontSize, "64px");
});

test("leading-[<value>] and tracking-[<value>] map to line-height and letter-spacing", async () => {
  const { applyArbitraryTextStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({
    className: "text-[43px] leading-[1.04] tracking-[-0.04em]",
  });

  applyArbitraryTextStyles(container);

  assert.equal(container.style.fontSize, "43px");
  assert.equal(container.style.lineHeight, "1.04");
  assert.equal(container.style.letterSpacing, "-0.04em");
});

test("an element with no arbitrary text classes is left untouched", async () => {
  const { applyArbitraryTextStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({ className: "flex items-center gap-2" });

  applyArbitraryTextStyles(container);

  assert.deepEqual(container.style, {});
});

test("descendants are walked recursively, each independently styled", async () => {
  const { applyArbitraryTextStyles } = await importSmartSlideArbitraryStyles();
  const heading = fakeElement({ className: "text-[64px]" });
  const nestedBadge = fakeElement({ className: "text-[11px]" });
  const wrapper = fakeElement({ className: "flex", children: [nestedBadge] });
  const container = fakeElement({
    className: "relative h-[720px]",
    children: [heading, wrapper],
  });

  applyArbitraryTextStyles(container);

  assert.equal(heading.style.fontSize, "64px");
  assert.equal(nestedBadge.style.fontSize, "11px");
  // The container itself has no text-[...] class, so no fontSize should be
  // set on it despite being processed too (it's included precisely so a
  // root element carrying such a class - not just its children - is caught).
  assert.equal(container.style.fontSize, undefined);
});

test("the root container itself is styled when it carries an arbitrary text class", async () => {
  const { applyArbitraryTextStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({ className: "text-[20px] h-[720px]" });

  applyArbitraryTextStyles(container);

  assert.equal(container.style.fontSize, "20px");
});

// ---------------------------------------------------------------------------
// applyArbitraryGridStyles - same async-Tailwind-compile race as the text
// fix above, for grid-cols-[...] column splits. Reproduced from a real
// generated slide: a `grid-cols-[0.38fr_0.62fr]` text/chart split, unstyled
// until the shared engine compiles it, collapsed to a single track and left
// a nested 3-column stat row far narrower than intended - narrow enough that
// "Desktop" wrapped mid-word in a real screenshot.
// ---------------------------------------------------------------------------

test("grid-cols-[<fr-list>] is applied as an inline grid-template-columns, with underscores restored to spaces", async () => {
  const { applyArbitraryGridStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({
    className: "grid grid-cols-[0.38fr_0.62fr] gap-10",
  });

  applyArbitraryGridStyles(container);

  assert.equal(container.style.gridTemplateColumns, "0.38fr 0.62fr");
});

test("a grid-cols-[...] value containing a CSS function with commas is captured whole", async () => {
  // A real value seen in this app's own generated slides -
  // grid-cols-[190px_repeat(5,1fr)] - the comma inside repeat() must not be
  // mistaken for the end of the bracketed value.
  const { applyArbitraryGridStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({
    className: "grid grid-cols-[190px_repeat(5,1fr)]",
  });

  applyArbitraryGridStyles(container);

  assert.equal(container.style.gridTemplateColumns, "190px repeat(5,1fr)");
});

test("an element with no arbitrary grid classes is left untouched", async () => {
  const { applyArbitraryGridStyles } = await importSmartSlideArbitraryStyles();
  const container = fakeElement({ className: "grid grid-cols-3 gap-3" });

  applyArbitraryGridStyles(container);

  assert.deepEqual(container.style, {});
});

test("grid descendants are walked recursively, each independently styled", async () => {
  const { applyArbitraryGridStyles } = await importSmartSlideArbitraryStyles();
  const outerSplit = fakeElement({
    className: "grid grid-cols-[0.38fr_0.62fr] gap-10",
  });
  const nestedStatRow = fakeElement({ className: "grid grid-cols-3 gap-3" });
  const wrapper = fakeElement({
    className: "flex flex-col",
    children: [nestedStatRow],
  });
  const container = fakeElement({
    className: "relative h-[720px]",
    children: [outerSplit, wrapper],
  });

  applyArbitraryGridStyles(container);

  assert.equal(outerSplit.style.gridTemplateColumns, "0.38fr 0.62fr");
  // grid-cols-3 is a standard (non-arbitrary) utility - not this function's
  // job, since the standard scale is compiled early/globally and isn't
  // exposed to the same race the arbitrary-value classes are.
  assert.equal(nestedStatRow.style.gridTemplateColumns, undefined);
  assert.equal(container.style.gridTemplateColumns, undefined);
});

test("applyArbitraryTextStyles and applyArbitraryGridStyles are independent - each only touches its own properties", async () => {
  const { applyArbitraryTextStyles, applyArbitraryGridStyles } =
    await importSmartSlideArbitraryStyles();
  const container = fakeElement({
    className: "text-[28px] grid-cols-[0.38fr_0.62fr]",
  });

  applyArbitraryTextStyles(container);
  applyArbitraryGridStyles(container);

  assert.equal(container.style.fontSize, "28px");
  assert.equal(container.style.gridTemplateColumns, "0.38fr 0.62fr");
});

// ---------------------------------------------------------------------------
// applyGridItemMinWidthGuard - the actual fix for the reported "55%"/
// "Desktop" mid-word-wrap bug. Root cause confirmed by live reproduction
// (Puppeteer against the real running app, not static analysis): a grid or
// flex item's min-width defaults to its own content's min-content size, and
// that default overrides a `fr` track's or flex-basis's proportional share.
// A fixed-intrinsic-width child (a <canvas>, concretely) forces its column
// to its content's width, stealing space from sibling columns. This
// reproduced on every single load (not intermittently), which is what ruled
// out the Tailwind-compile race applyArbitraryGridStyles guards against.
// ---------------------------------------------------------------------------

test("a grid child with no explicit min-w-* class gets min-width:0", async () => {
  const { applyGridItemMinWidthGuard } = await importSmartSlideArbitraryStyles();
  const textColumn = fakeElement({ className: "flex flex-col justify-center" });
  const chartPanel = fakeElement({ className: "border border-black p-4" });
  const container = fakeElement({
    className: "grid grid-cols-[0.38fr_0.62fr] gap-10",
    children: [textColumn, chartPanel],
  });

  applyGridItemMinWidthGuard(container);

  assert.equal(textColumn.style.minWidth, "0px");
  assert.equal(chartPanel.style.minWidth, "0px");
});

test("a flex child with no explicit min-w-* class also gets min-width:0 - the same CSS default applies to flex items", async () => {
  const { applyGridItemMinWidthGuard } = await importSmartSlideArbitraryStyles();
  const item = fakeElement({ className: "p-4" });
  const container = fakeElement({
    className: "flex items-center gap-4",
    children: [item],
  });

  applyGridItemMinWidthGuard(container);

  assert.equal(item.style.minWidth, "0px");
});

test("min-w-0 already present on a child still gets the inline style, not skipped - the class alone doesn't guarantee the shared engine has compiled it yet", async () => {
  const { applyGridItemMinWidthGuard } = await importSmartSlideArbitraryStyles();
  const child = fakeElement({ className: "min-w-0 flex-1" });
  const container = fakeElement({ className: "flex", children: [child] });

  applyGridItemMinWidthGuard(container);

  assert.equal(child.style.minWidth, "0px");
});

test("an explicit, different min-w-* class is never overridden", async () => {
  const { applyGridItemMinWidthGuard } = await importSmartSlideArbitraryStyles();
  const fixedChild = fakeElement({ className: "min-w-[200px]" });
  const fullChild = fakeElement({ className: "min-w-full" });
  const container = fakeElement({
    className: "flex",
    children: [fixedChild, fullChild],
  });

  applyGridItemMinWidthGuard(container);

  assert.equal(fixedChild.style.minWidth, undefined);
  assert.equal(fullChild.style.minWidth, undefined);
});

test("a container that is neither flex nor grid is left alone", async () => {
  const { applyGridItemMinWidthGuard } = await importSmartSlideArbitraryStyles();
  const child = fakeElement({ className: "p-4" });
  const container = fakeElement({ className: "block", children: [child] });

  applyGridItemMinWidthGuard(container);

  assert.equal(child.style.minWidth, undefined);
});

test("nested flex/grid containers are each guarded independently, at every depth", async () => {
  const { applyGridItemMinWidthGuard } = await importSmartSlideArbitraryStyles();
  const innermost = fakeElement({ className: "p-2" });
  const innerRow = fakeElement({
    className: "grid grid-cols-3 gap-3",
    children: [innermost],
  });
  const outer = fakeElement({
    className: "grid grid-cols-[0.38fr_0.62fr]",
    children: [innerRow],
  });

  applyGridItemMinWidthGuard(outer);

  // innerRow is both a grid CONTAINER (its own children get guarded) and a
  // grid ITEM of the outer split (it gets guarded itself too).
  assert.equal(innerRow.style.minWidth, "0px");
  assert.equal(innermost.style.minWidth, "0px");
});
