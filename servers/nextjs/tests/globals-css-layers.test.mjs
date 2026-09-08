import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import postcss from "postcss";
import tailwindcss from "tailwindcss";

// This app runs two Tailwind major versions at once: v3 compiles globals.css
// at build time, while Smart-mode/TemplateV2 slide content is styled at
// runtime by the v4 browser JIT. v3's `@tailwind base` used to expand to
// plain, UNLAYERED CSS - including preflight's grey default border-color -
// which silently beat every v4 (layered) border-color/border-width utility
// a Smart slide used that v3 doesn't also emit (i.e. any class that doesn't
// happen to appear in this app's own .tsx source). The fix nests v3's
// preflight inside its own named cascade layer (`tw3-base`), declared
// before that layer's contents so it sits above v4's own preflight but
// below v4's utilities. This test compiles the REAL globals.css through the
// REAL installed Tailwind v3 pipeline and asserts the result by brace
// balance (not substring proximity, which is fooled by this very file's own
// explanatory comment containing the literal string "border-color") - so a
// future edit or Tailwind version bump can't silently un-layer preflight
// again without this test failing.

const globalsCssUrl = new URL("../app/globals.css", import.meta.url);

async function compileGlobalsCss() {
  const css = await readFile(globalsCssUrl, "utf8");
  const result = await postcss([
    tailwindcss({
      content: [{ raw: '<div class="border-b"></div>' }],
      config: new URL("../tailwind.config.ts", import.meta.url).pathname,
    }),
  ]).process(css, { from: globalsCssUrl.pathname });
  return result.css;
}

function isInsideBraceRange(css, openIndex, targetIndex) {
  let depth = 0;
  for (let i = openIndex; i < css.length && i <= targetIndex; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}") depth--;
    if (i === targetIndex) return depth > 0;
  }
  return false;
}

test("globals.css declares the tw3-base layer order statement as its first rule", async () => {
  const source = await readFile(globalsCssUrl, "utf8");
  const withoutLeadingComment = source.replace(/\/\*[\s\S]*?\*\//, "").trimStart();

  assert.ok(
    withoutLeadingComment.startsWith(
      "@layer theme, base, tw3-base, components, utilities;",
    ),
    "the layer-order statement must be the first real rule, so it registers " +
      "before the v4 runtime's own later @layer statement can establish a " +
      "different order",
  );
});

test("v3 preflight's border-color lands inside the tw3-base layer, not unlayered", async () => {
  const compiled = await compileGlobalsCss();

  const layerStart = compiled.indexOf("@layer tw3-base {");
  assert.notEqual(layerStart, -1, "expected a tw3-base layer block in the compiled output");

  const preflightBorderColor = compiled.indexOf(
    "border-color: #e5e7eb",
    layerStart,
  );
  assert.notEqual(
    preflightBorderColor,
    -1,
    "expected preflight's default border-color declaration after the tw3-base layer opens",
  );

  assert.ok(
    isInsideBraceRange(compiled, layerStart, preflightBorderColor),
    "preflight's border-color must be INSIDE the tw3-base layer block, so it " +
      "loses to a v4 utility in the higher-priority utilities layer",
  );
});

test("a v3 utility class stays unlayered, so app chrome keeps its existing priority", async () => {
  const compiled = await compileGlobalsCss();

  const layerStart = compiled.indexOf("@layer tw3-base {");
  let depth = 0;
  let layerCloseIndex = -1;
  for (let i = layerStart + "@layer tw3-base {".length - 1; i < compiled.length; i++) {
    if (compiled[i] === "{") depth++;
    else if (compiled[i] === "}") {
      depth--;
      if (depth === 0) {
        layerCloseIndex = i;
        break;
      }
    }
  }
  assert.notEqual(layerCloseIndex, -1, "expected the tw3-base layer block to close");

  const utilityIndex = compiled.indexOf(".border-b{", layerCloseIndex);
  assert.notEqual(
    utilityIndex,
    -1,
    "expected a plain .border-b utility rule (emitted because 'border-b' " +
      "appears in this app's own source) after the tw3-base block closes",
  );

  const between = compiled.slice(layerCloseIndex, utilityIndex);
  assert.ok(
    !/@layer[^{]*\{/.test(between),
    ".border-b must not be nested inside any @layer block - it needs to stay " +
      "unlayered so it keeps beating everything, exactly as before this fix",
  );
});
