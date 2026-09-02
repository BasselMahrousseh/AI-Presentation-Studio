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
