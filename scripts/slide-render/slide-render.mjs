#!/usr/bin/env node
/**
 * Keeps the slide-render code that Studio's headless exporter uses identical to the copy the
 * Workspace UI's editor uses, so an exported PPTX/PDF keeps matching what the user saw on screen.
 *
 * The shared set is not hand-listed. It is the import closure of the export page
 * (`app/(export)/pdf-maker/page.tsx`), minus files the host app must provide itself (state, API
 * client, telemetry, UI kit). Adding an import to the renderer therefore changes the closure, which
 * fails `check` until the lock is regenerated and the change is synced into Workspace.
 *
 *   node scripts/slide-render/slide-render.mjs check            # CI: closure + hashes match the lock
 *   node scripts/slide-render/slide-render.mjs update           # rewrite the lock after a change
 *   node scripts/slide-render/slide-render.mjs sync <dir>       # copy into <workspace>/src/features/studio
 *   node scripts/slide-render/slide-render.mjs report           # list shared and host-owned files
 *
 * Files keep their relative paths under the target, so relative imports stay valid. Only `@/`
 * alias imports are rewritten to `@/features/studio/`.
 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../..");
const APP_ROOT = path.join(REPO_ROOT, "servers/nextjs");
const LOCK_PATH = path.join(HERE, "slide-render.lock.json");
const TARGET_PREFIX = "@/features/studio/";

const ENTRIES = ["app/(export)/pdf-maker/page.tsx"];

/** Renderer-only glue. It is traversed (its imports matter) but never copied into Workspace. */
const RENDERER_ONLY = [/^app\/\(export\)\//];

/**
 * Modules the host application supplies at the same relative path: state, API client, telemetry
 * and the UI kit. Workspace owns and ports these itself, so they are not synced.
 */
const HOST_OWNED = [
  /^store\//,
  /^app\/\(presentation-generator\)\/services\//,
  /^components\/ui\//,
  /^utils\/(api|apiErrorMessages|mixpanel|analytics|chatgptAuth|codexModels|providerConstants|storeHelpers|presentationLimits)\.ts$/,
  /^types\/llm_config\.ts$/,
];

const EXTENSIONS = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.tsx"];
const SOURCE_FILE = /\.(tsx?|jsx?|mjs)$/;
const SPECIFIER_SOURCE =
  /(\bfrom\s*)(['"])([^'"]+)\2|(\bimport\s*)(['"])([^'"]+)\5|(\bimport\(\s*)(['"])([^'"]+)\8(\s*\))|(\brequire\(\s*)(['"])([^'"]+)\12(\s*\))/g;

const sha256 = (data) => createHash("sha256").update(data).digest("hex");
const toPosix = (p) => p.split(path.sep).join("/");

function resolveSpecifier(fromFile, specifier) {
  let base;
  if (specifier.startsWith("@/")) base = path.join(APP_ROOT, specifier.slice(2));
  else if (specifier.startsWith(".")) base = path.resolve(path.dirname(fromFile), specifier);
  else return null; // a package
  for (const ext of EXTENSIONS) {
    const candidate = base + ext;
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(
    `Unresolvable import "${specifier}" in ${toPosix(path.relative(APP_ROOT, fromFile))}`
  );
}

function computeClosure() {
  const seen = new Set();
  const visit = (file) => {
    if (seen.has(file)) return;
    seen.add(file);
    if (!SOURCE_FILE.test(file)) return;
    const source = fs.readFileSync(file, "utf8");
    for (const match of source.matchAll(SPECIFIER_SOURCE)) {
      const specifier = match[3] ?? match[6] ?? match[9] ?? match[13];
      const resolved = resolveSpecifier(file, specifier);
      if (resolved) visit(resolved);
    }
  };
  for (const entry of ENTRIES) visit(path.join(APP_ROOT, entry));
  return [...seen].map((f) => toPosix(path.relative(APP_ROOT, f))).sort();
}

function classify(files) {
  const shared = [];
  const hostOwned = [];
  for (const file of files) {
    if (RENDERER_ONLY.some((re) => re.test(file))) continue;
    if (HOST_OWNED.some((re) => re.test(file))) hostOwned.push(file);
    else shared.push(file);
  }
  return { shared, hostOwned };
}

function rewriteAliases(source) {
  return source.replace(SPECIFIER_SOURCE, (whole, ...groups) => {
    const specifier = groups[2] ?? groups[5] ?? groups[8] ?? groups[12];
    if (!specifier?.startsWith("@/")) return whole;
    return whole.replace(specifier, TARGET_PREFIX + specifier.slice(2));
  });
}

const header = (file) =>
  `// GENERATED from AI-Presentation-Studio/servers/nextjs/${file}. Do not edit here: change it in\n` +
  `// Studio and run scripts/slide-render/slide-render.mjs sync, or the exporter and editor drift.\n`;

function syncedContent(file) {
  const source = fs.readFileSync(path.join(APP_ROOT, file), "utf8");
  return SOURCE_FILE.test(file) ? header(file) + rewriteAliases(source) : source;
}

function buildLock() {
  const { shared, hostOwned } = classify(computeClosure());
  const source = {};
  const synced = {};
  for (const file of shared) {
    source[file] = sha256(fs.readFileSync(path.join(APP_ROOT, file)));
    synced[file] = sha256(syncedContent(file));
  }
  return { entries: ENTRIES, hostOwned, source, synced };
}

function readLock() {
  return fs.existsSync(LOCK_PATH) ? JSON.parse(fs.readFileSync(LOCK_PATH, "utf8")) : null;
}

const writeLock = (lock, target) =>
  fs.writeFileSync(target, JSON.stringify(lock, null, 2) + "\n");

function diffLocks(committed, current) {
  const problems = [];
  const before = committed?.source ?? {};
  for (const file of Object.keys(current.source)) {
    if (!(file in before)) problems.push(`new shared file (not in lock): ${file}`);
    else if (before[file] !== current.source[file]) problems.push(`changed since lock: ${file}`);
  }
  for (const file of Object.keys(before)) {
    if (!(file in current.source)) problems.push(`no longer shared (removed or now host-owned): ${file}`);
  }
  const hostBefore = new Set(committed?.hostOwned ?? []);
  for (const file of current.hostOwned) {
    if (!hostBefore.has(file)) problems.push(`new host-owned file (Workspace must provide it): ${file}`);
  }
  for (const file of hostBefore) {
    if (!current.hostOwned.includes(file)) problems.push(`host-owned file no longer imported: ${file}`);
  }
  return problems;
}

function check() {
  const committed = readLock();
  if (!committed) return fail("No lock file. Run: node scripts/slide-render/slide-render.mjs update");
  const problems = diffLocks(committed, buildLock());
  if (problems.length) {
    return fail(
      "Slide-render code drifted from the lock:\n  " +
        problems.join("\n  ") +
        "\nRun `slide-render.mjs update`, then `slide-render.mjs sync <workspace>/src/features/studio` and commit both repos."
    );
  }
  console.log(`slide-render: ${Object.keys(committed.source).length} shared files match the lock.`);
}

function sync(targetDir) {
  if (!targetDir) return fail("Usage: slide-render.mjs sync <workspace>/src/features/studio");
  const committed = readLock();
  const current = buildLock();
  const problems = diffLocks(committed, current);
  if (problems.length) {
    return fail("Refusing to sync: the lock is stale.\n  " + problems.join("\n  ") + "\nRun `update` first.");
  }
  const target = path.resolve(targetDir);
  // Remove copies of files that stopped being shared, using the previous target lock.
  const previousLockPath = path.join(target, "slide-render.lock.json");
  if (fs.existsSync(previousLockPath)) {
    const previous = JSON.parse(fs.readFileSync(previousLockPath, "utf8"));
    for (const file of Object.keys(previous.synced ?? {})) {
      if (!(file in current.synced)) fs.rmSync(path.join(target, file), { force: true });
    }
  }
  for (const file of Object.keys(current.synced)) {
    const destination = path.join(target, file);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, syncedContent(file));
  }
  writeLock(current, previousLockPath);
  fs.copyFileSync(path.join(HERE, "verify-copies.mjs"), path.join(target, "verify-slide-render.mjs"));
  console.log(
    `slide-render: synced ${Object.keys(current.synced).length} files into ${target}.\n` +
      `Host-owned (Workspace must provide at the same relative paths): ${current.hostOwned.length} files.`
  );
}

function report() {
  const { shared, hostOwned } = classify(computeClosure());
  console.log(`SHARED (${shared.length}):\n  ${shared.join("\n  ")}`);
  console.log(`\nHOST-OWNED (${hostOwned.length}):\n  ${hostOwned.join("\n  ")}`);
}

function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

const [command, argument] = process.argv.slice(2);
switch (command) {
  case "check":
    check();
    break;
  case "update":
    writeLock(buildLock(), LOCK_PATH);
    console.log(`slide-render: wrote ${toPosix(path.relative(REPO_ROOT, LOCK_PATH))}`);
    break;
  case "sync":
    sync(argument);
    break;
  case "report":
    report();
    break;
  default:
    fail("Usage: slide-render.mjs <check|update|sync <dir>|report>");
}
