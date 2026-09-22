import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function importChecker() {
  const dir = await mkdtemp(path.join(os.tmpdir(), "export-output-check-"));
  const outfile = path.join(dir, "check.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["lib/export-output-check.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

/** Minimal zip (stored, no compression) with the given entry names, enough for a central directory. */
function zipWith(names) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const name of names) {
    const nameBuf = Buffer.from(name);
    const local = Buffer.alloc(30 + nameBuf.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(nameBuf.length, 26);
    nameBuf.copy(local, 30);
    const central = Buffer.alloc(46 + nameBuf.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt32LE(offset, 42);
    nameBuf.copy(central, 46);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const centralDir = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(names.length, 8);
  eocd.writeUInt16LE(names.length, 10);
  eocd.writeUInt32LE(centralDir.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, centralDir, eocd]);
}

test("counts only ppt/slides/slideN.xml entries in a PPTX", async () => {
  const { countPptxSlides } = await importChecker();
  const file = zipWith(["[Content_Types].xml", "ppt/presentation.xml", "ppt/slides/slide1.xml", "ppt/slides/slide2.xml", "ppt/slides/_rels/slide1.xml.rels", "ppt/slideLayouts/slideLayout1.xml"]);
  assert.equal(countPptxSlides(file), 2);
  assert.equal(countPptxSlides(zipWith(["[Content_Types].xml", "ppt/presentation.xml"])), 0);
});

test("rejects an empty or truncated export, accepts a complete one", async () => {
  const { checkExportOutput } = await importChecker();
  const empty = zipWith(["ppt/presentation.xml"]);
  assert.deepEqual(checkExportOutput("pptx", empty, 12), { ok: false, reason: "the PPTX contains 0 slides" });
  assert.equal(checkExportOutput("pptx", empty, null).ok, false); // empty is bad even if the deck size is unknown
  const partial = zipWith(["ppt/slides/slide1.xml", "ppt/slides/slide2.xml"]);
  assert.equal(checkExportOutput("pptx", partial, 12).ok, false);
  const full = zipWith(Array.from({ length: 12 }, (_, i) => `ppt/slides/slide${i + 1}.xml`));
  assert.equal(checkExportOutput("pptx", full, 12).ok, true);
});

test("PDF page count comes from the page tree, and unknown is not judged", async () => {
  const { countPdfPages, checkExportOutput } = await importChecker();
  const pdf = Buffer.from("%PDF-1.4\n1 0 obj\n<< /Type /Pages /Kids [2 0 R] /Count 6 >>\nendobj\n%%EOF", "latin1");
  assert.equal(countPdfPages(pdf), 6);
  assert.equal(checkExportOutput("pdf", pdf, 6).ok, true);
  assert.equal(checkExportOutput("pdf", pdf, 12).ok, false);
  const opaque = Buffer.from("%PDF-1.5 compressed object streams only", "latin1");
  assert.equal(countPdfPages(opaque), null);
  assert.equal(checkExportOutput("pdf", opaque, 6).ok, true);
});

test("the real 0-slide export from the bug report is rejected", async () => {
  const fs = await import("node:fs");
  const sample = process.env.EMPTY_PPTX_SAMPLE;
  if (!sample || !fs.existsSync(sample)) return;
  const { checkExportOutput } = await importChecker();
  assert.equal(checkExportOutput("pptx", fs.readFileSync(sample), 12).ok, false);
});
