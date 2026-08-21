import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { after, before } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const nextRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
let tempDirectory;
let providerConstants;
let storeHelpers;

before(async () => {
  tempDirectory = await mkdtemp(
    path.join(os.tmpdir(), "presenton-provider-settings-"),
  );
  const providersOutput = path.join(tempDirectory, "providers.mjs");
  const helpersOutput = path.join(tempDirectory, "store-helpers.mjs");

  await Promise.all([
    build({
      entryPoints: [path.join(nextRoot, "utils/providerConstants.ts")],
      bundle: true,
      platform: "node",
      format: "esm",
      outfile: providersOutput,
      logLevel: "silent",
    }),
    build({
      entryPoints: [path.join(nextRoot, "utils/storeHelpers.ts")],
      bundle: true,
      platform: "node",
      format: "esm",
      outfile: helpersOutput,
      logLevel: "silent",
    }),
  ]);

  providerConstants = await import(pathToFileURL(providersOutput).href);
  storeHelpers = await import(pathToFileURL(helpersOutput).href);
});

after(async () => {
  if (tempDirectory) {
    await rm(tempDirectory, { recursive: true, force: true });
  }
});

test("Presenton is available in the Settings text-provider selector", () => {
  assert.deepEqual(providerConstants.LLM_PROVIDERS.presenton, {
    value: "presenton",
    label: "Presenton",
    description: "Generate with your connected Presenton Cloud account",
    icon: "/providers/presenton.png",
  });
});

test("Presenton selection does not require local model or API-key fields", () => {
  assert.equal(
    storeHelpers.getLLMConfigValidationError({ LLM: "presenton" }),
    null,
  );
});
