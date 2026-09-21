#!/usr/bin/env node
/**
 * Workspace-side drift check. Copied next to the synced files as `verify-slide-render.mjs`.
 * Fails if any synced file was edited, deleted or added by hand, since these files are generated
 * from AI-Presentation-Studio (see the header in each file).
 *
 *   node src/features/studio/verify-slide-render.mjs
 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const lock = JSON.parse(fs.readFileSync(path.join(DIR, "slide-render.lock.json"), "utf8"));
const problems = [];

for (const [file, expected] of Object.entries(lock.synced)) {
  const full = path.join(DIR, file);
  if (!fs.existsSync(full)) {
    problems.push(`missing: ${file}`);
    continue;
  }
  const actual = createHash("sha256").update(fs.readFileSync(full)).digest("hex");
  if (actual !== expected) problems.push(`edited by hand: ${file}`);
}

for (const file of lock.hostOwned) {
  if (!fs.existsSync(path.join(DIR, file))) problems.push(`host-owned file not provided: ${file}`);
}

if (problems.length) {
  console.error(
    "Studio slide-render copies drifted from the lock:\n  " +
      problems.join("\n  ") +
      "\nRe-run `slide-render.mjs sync` from AI-Presentation-Studio instead of editing these files."
  );
  process.exit(1);
}
console.log(`verify-slide-render: ${Object.keys(lock.synced).length} synced files match the lock.`);
