import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const presentationCardUrl = new URL(
  "../app/(presentation-generator)/(dashboard)/dashboard/components/PresentationCard.tsx",
  import.meta.url,
);

test("dashboard delete confirmation renders in a modal layer above dashboard chrome", async () => {
  const source = await readFile(presentationCardUrl, "utf8");

  assert.match(source, /<Dialog\s+[\s\S]*?open=\{showDeleteDialog\}/);
  assert.match(source, /overlayClassName="z-\[100\][^"]*"/);
  assert.match(source, /className="z-\[101\][^"]*"/);
  assert.match(source, /<Popover open=\{showActions\}/);
  assert.match(source, /setShowActions\(false\);\s+setShowDeleteDialog\(true\);/);
  assert.doesNotMatch(source, /showDeleteDialog && \(/);
});
