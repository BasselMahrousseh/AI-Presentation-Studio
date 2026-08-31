#!/usr/bin/env node
/**
 * CLI bridge used by FastAPI to extract document text with LiteParse.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { LiteParse } from "@llamaindex/liteparse";

function readArg(name) {
  const idx = process.argv.indexOf(name);
  return idx === -1 ? null : (process.argv[idx + 1] ?? null);
}

function parseBool(value, fallback) {
  if (value == null || value === "") return fallback;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  return fallback;
}

function toNumber(value, fallback, minimum, maximum) {
  if (value == null || value === "") return fallback;
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(Math.max(parsed, minimum), maximum);
}

function normalizeOcrLanguage(value) {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "eng";
  return normalized.includes(",")
    ? normalized.split(",").map((part) => part.trim()).filter(Boolean).join("+")
    : normalized;
}

function emit(payload, exitCode = 0) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
  process.exit(exitCode);
}

const bridgeMode = String(readArg("--python-bridge") ?? "json").trim().toLowerCase();
const usePlainOutput = bridgeMode === "plain";

function fail(message, exitCode) {
  if (usePlainOutput) {
    process.stderr.write(`${message}\n`);
    process.exit(exitCode);
  }
  emit({ ok: false, error: message }, exitCode);
}

const filePath = readArg("--file");
if (!filePath) fail("Missing required --file argument", 2);

const resolvedPath = path.resolve(filePath);
if (!fs.existsSync(resolvedPath)) fail(`File not found: ${resolvedPath}`, 2);

const ocrEnabled = parseBool(readArg("--ocr-enabled"), true);
const dpi = toNumber(readArg("--dpi"), 150, 72, 600);
const numWorkers = toNumber(readArg("--num-workers"), Math.max(os.cpus().length - 2, 1), 1, 64);
const ocrLanguage = normalizeOcrLanguage(
  process.env.LITEPARSE_OCR_LANGUAGE || readArg("--ocr-language") || "eng"
);
const outputFormat = String(readArg("--output-format") || "text").trim().toLowerCase() === "json"
  ? "json"
  : "text";
const ocrServerUrl = readArg("--ocr-server-url") || process.env.LITEPARSE_OCR_SERVER_URL || undefined;
const tessdataPath = readArg("--tessdata-path") || process.env.LITEPARSE_TESSDATA_PATH || process.env.TESSDATA_PREFIX || undefined;

try {
  const config = { ocrEnabled, ocrLanguage, outputFormat, dpi, numWorkers };
  if (ocrServerUrl) config.ocrServerUrl = ocrServerUrl;
  if (tessdataPath) config.tessdataPath = tessdataPath;

  const result = await new LiteParse(config).parse(resolvedPath, true);
  const text = result?.text ?? "";
  if (usePlainOutput) {
    process.stdout.write(text);
    process.exit(0);
  }
  emit({
    ok: true,
    filePath: resolvedPath,
    text,
    pageCount: Array.isArray(result?.pages) ? result.pages.length : 0,
    ocr: { engine: ocrServerUrl ? "http" : "tesseract", ocrLanguage, ocrEnabled, dpi, numWorkers },
  });
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  const stack = error instanceof Error ? error.stack : undefined;
  if (usePlainOutput) {
    if (stack) process.stderr.write(`${stack}\n`);
    process.stderr.write(`${message}\n`);
    process.exit(1);
  }
  if (stack) process.stderr.write(`${stack}\n`);
  emit({ ok: false, filePath: resolvedPath, error: message }, 1);
}
