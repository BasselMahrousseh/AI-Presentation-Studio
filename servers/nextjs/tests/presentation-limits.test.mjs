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

async function importPresentationLimits() {
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "presentation-limits-"));
  const outfile = path.join(tempDirectory, "presentation-limits.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["utils/presentationLimits.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

test("MAX_OUTLINE_CONTENT_WORDS matches the backend's raised limit", async () => {
  const { MAX_OUTLINE_CONTENT_WORDS } = await importPresentationLimits();
  assert.equal(MAX_OUTLINE_CONTENT_WORDS, 300);
});

test("trimTextToWordLimit excludes a half-written table row", async () => {
  const { trimTextToWordLimit } = await importPresentationLimits();

  const header = "| Priority | Model | Role |";
  const separator = "|---|---|---|";
  const row1 = "| 1 | GPT-OSS-120B | Core reasoning |";
  const row2 = "| 2 | Qwen3-VL-235B | Documents |";
  const row3 = "| 3 | Qwen3.5-397B | Premium generalist |";
  const content = [header, separator, row1, row2, row3].join("\n");

  // "|" counts as its own word: header=7, separator=1, row1=8, row2=7 -> 23
  // words before row3; row3 itself is 8 words. A limit of 26 lands 3 words
  // into row3 under a naive word-count-only cutoff (mid-row).
  const trimmed = trimTextToWordLimit(content, 26);

  assert.ok(trimmed.includes(row1));
  assert.ok(trimmed.includes(row2));
  assert.ok(!trimmed.includes(row3));
  assert.ok(!trimmed.includes("| 3 |"));
});

test("trimTextToWordLimit falls back to a word cutoff for a single long line", async () => {
  const { trimTextToWordLimit } = await importPresentationLimits();

  const content = Array.from({ length: 10 }, (_, i) => `word${i}`).join(" ");

  assert.equal(trimTextToWordLimit(content, 5), "word0 word1 word2 word3 word4");
});

test("trimTextToWordLimit leaves text under the limit unchanged", async () => {
  const { trimTextToWordLimit } = await importPresentationLimits();

  const content = "## Title\nSome short body text.";

  assert.equal(trimTextToWordLimit(content, 300), content);
});
