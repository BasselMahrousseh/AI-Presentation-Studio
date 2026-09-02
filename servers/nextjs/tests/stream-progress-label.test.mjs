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

async function importStreamProgressLabel() {
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "stream-progress-label-"));
  const outfile = path.join(tempDirectory, "stream-progress-label.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: [
      "app/(presentation-generator)/presentation/utils/streamProgressLabel.ts",
    ],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

const base = {
  isStreaming: true,
  streamTotalSlides: null,
  streamGeneratedSlides: null,
  streamStageMessage: null,
  slidesGenerated: 0,
};

test("an e& deck counts only the slides actually being generated", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  // A 10-slide e& request: the backend reports 12 total (10 generated + the
  // fixed cover and thank-you slides) but only the 10 are ever streamed. The
  // user asked for 10, so the progress must say 10 - reporting "of 12" counts
  // slides they never requested and cannot watch arrive.
  assert.equal(
    getStreamProgressLabel({
      ...base,
      streamTotalSlides: 12,
      streamGeneratedSlides: 10,
      slidesGenerated: 3,
    }),
    "Generating slide 4 of 10",
  );
});

test("a non-e& deck is unchanged when both counts agree", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  assert.equal(
    getStreamProgressLabel({
      ...base,
      streamTotalSlides: 8,
      streamGeneratedSlides: 8,
      slidesGenerated: 3,
    }),
    "Generating slide 4 of 8",
  );
});

test("falls back to the deck total when the generated count is absent", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  // Older backends, and the replay path for an already-generated deck, send
  // only total_slides - the label must still work rather than going blank.
  for (const missing of [null, undefined, 0]) {
    assert.equal(
      getStreamProgressLabel({
        ...base,
        streamTotalSlides: 8,
        streamGeneratedSlides: missing,
        slidesGenerated: 3,
      }),
      "Generating slide 4 of 8",
    );
  }
});

test("the pre-first-slide message uses the generated count too", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  assert.equal(
    getStreamProgressLabel({
      ...base,
      streamTotalSlides: 12,
      streamGeneratedSlides: 10,
      slidesGenerated: 0,
    }),
    "Preparing 10 slides",
  );
});

test("the fixed slides arriving at the end read as finishing, not overflow", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  // Once generation ends the cover and thank-you slides are spliced in, so
  // slides.length (12) exceeds the generated count (10). That must not produce
  // "Generating slide 13 of 10".
  assert.equal(
    getStreamProgressLabel({
      ...base,
      streamTotalSlides: 12,
      streamGeneratedSlides: 10,
      slidesGenerated: 12,
    }),
    "Finishing up",
  );
});

test("a stage message still wins before any slide arrives", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  assert.equal(
    getStreamProgressLabel({
      ...base,
      streamTotalSlides: 12,
      streamGeneratedSlides: 10,
      streamStageMessage: "Designing the complete presentation",
      slidesGenerated: 0,
    }),
    "Designing the complete presentation",
  );
});

test("nothing is shown when the stream is not running", async () => {
  const { getStreamProgressLabel } = await importStreamProgressLabel();

  assert.equal(
    getStreamProgressLabel({ ...base, isStreaming: false, streamGeneratedSlides: 10 }),
    null,
  );
});
