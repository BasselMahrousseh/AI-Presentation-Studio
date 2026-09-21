import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SCRIPT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../scripts/slide-render/slide-render.mjs"
);
const run = (...args) =>
  spawnSync(process.execPath, [SCRIPT, ...args], { encoding: "utf8" });

test("shared slide-render set matches the committed lock", () => {
  const result = run("check");
  assert.equal(result.status, 0, result.stderr);
});

test("sync produces copies whose own verifier passes, and catches a hand edit", () => {
  const target = fs.mkdtempSync(path.join(os.tmpdir(), "slide-render-"));
  try {
    const synced = run("sync", target);
    assert.equal(synced.status, 0, synced.stderr);

    const lock = JSON.parse(fs.readFileSync(path.join(target, "slide-render.lock.json"), "utf8"));
    // Workspace supplies these itself; stub them so only the copies are under test.
    for (const file of lock.hostOwned) {
      const destination = path.join(target, file);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.writeFileSync(destination, "");
    }
    const verify = path.join(target, "verify-slide-render.mjs");
    execFileSync(process.execPath, [verify], { encoding: "utf8" });

    const edited = path.join(target, Object.keys(lock.synced)[0]);
    fs.appendFileSync(edited, "\n// hand edit\n");
    const drifted = spawnSync(process.execPath, [verify], { encoding: "utf8" });
    assert.equal(drifted.status, 1);
    assert.match(drifted.stderr, /edited by hand/);

    const first = fs.readFileSync(path.join(target, Object.keys(lock.synced)[1]), "utf8");
    assert.match(first, /^(\/\/ GENERATED|"use client"|'use client')/m);
    assert.doesNotMatch(first, /from ["']@\/(?!features\/studio\/)/);
  } finally {
    fs.rmSync(target, { recursive: true, force: true });
  }
});
