import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

// Tests AsyncSemaphore, the promise-based concurrency primitive backing
// EXPORT_BUNDLE_RENDER_SLOTS in lib/run-bundled-presentation-export.ts (see
// CLAUDE.md's "No concurrency cap on Chromium spawns" fix). That file itself
// is not exercised directly here - it depends on real filesystem paths, a
// real `node` child process, and a `@/` path-aliased import, which would
// make a hermetic unit test mostly a test of mocking infrastructure rather
// than of the concurrency logic. The semaphore is the actual new behavior,
// and `run-bundled-presentation-export.ts`'s own acquire/release call sites
// were verified by direct code review: `acquire()` sits immediately before
// the spawn, and `release()` is in a `finally` around it, so a failed or
// crashed export always gives its slot back - mirroring exactly what
// `test_run_task_releases_slot_on_failure_so_nothing_leaks` proves on the
// FastAPI side for the equivalent Python primitive.

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

async function importRuntimeLimits() {
  const tempDirectory = await mkdtemp(
    path.join(os.tmpdir(), "runtime-limits-"),
  );
  const outfile = path.join(tempDirectory, "runtime-limits.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["lib/runtime-limits.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

const { AsyncSemaphore } = await importRuntimeLimits();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("AsyncSemaphore never lets more than `max` holders run at once", async () => {
  const semaphore = new AsyncSemaphore(2);
  let current = 0;
  let peak = 0;

  async function task() {
    await semaphore.acquire();
    try {
      current += 1;
      peak = Math.max(peak, current);
      await sleep(20);
    } finally {
      current -= 1;
      semaphore.release();
    }
  }

  await Promise.all([task(), task(), task(), task(), task(), task()]);

  assert.equal(peak <= 2, true, `expected peak <= 2, got ${peak}`);
  assert.equal(current, 0);
});

test("a task that throws still releases its slot (finally-based release)", async () => {
  const semaphore = new AsyncSemaphore(1);
  let peak = 0;
  let current = 0;

  async function failingTask() {
    await semaphore.acquire();
    try {
      current += 1;
      peak = Math.max(peak, current);
      await sleep(5);
      throw new Error("simulated export failure");
    } finally {
      current -= 1;
      semaphore.release();
    }
  }

  for (let i = 0; i < 5; i += 1) {
    await assert.rejects(failingTask(), /simulated export failure/);
  }

  // If any prior failure had leaked its slot, later acquire() calls would
  // have queued forever and this test would time out rather than complete.
  assert.equal(peak, 1);
});

test("release() hands the slot directly to the longest-waiting caller (FIFO)", async () => {
  const semaphore = new AsyncSemaphore(1);
  const order = [];

  const first = (async () => {
    await semaphore.acquire();
    order.push("first-acquired");
    await sleep(20);
    semaphore.release();
  })();

  await sleep(5); // ensure `first` has genuinely acquired before the rest queue

  const second = (async () => {
    order.push("second-queued");
    await semaphore.acquire();
    order.push("second-acquired");
    semaphore.release();
  })();

  const third = (async () => {
    await sleep(2); // queue strictly after `second`
    order.push("third-queued");
    await semaphore.acquire();
    order.push("third-acquired");
    semaphore.release();
  })();

  await Promise.all([first, second, third]);

  assert.deepEqual(order, [
    "first-acquired",
    "second-queued",
    "third-queued",
    "second-acquired",
    "third-acquired",
  ]);
});

test("available slots never grow past `max` even with extra releases", async () => {
  const semaphore = new AsyncSemaphore(2);

  await semaphore.acquire();
  semaphore.release();
  semaphore.release(); // no matching acquire - must not push available above max

  let current = 0;
  let peak = 0;
  async function task() {
    await semaphore.acquire();
    current += 1;
    peak = Math.max(peak, current);
    await sleep(10);
    current -= 1;
    semaphore.release();
  }

  await Promise.all([task(), task(), task(), task()]);

  assert.equal(peak <= 2, true, `expected peak <= 2, got ${peak}`);
});
