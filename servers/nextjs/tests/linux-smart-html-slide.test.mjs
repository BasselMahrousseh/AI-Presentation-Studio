import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const smartHtmlSlideUrl = new URL(
  "../app/(presentation-generator)/components/SmartHtmlSlide.tsx",
  import.meta.url,
);
const communityPageUrl = new URL(
  "../app/(presentation-generator)/(dashboard)/community/components/CommunityPage.tsx",
  import.meta.url,
);
const communityDialogUrl = new URL(
  "../app/(presentation-generator)/(dashboard)/community/components/CommunityDesignPreviewDialog.tsx",
  import.meta.url,
);
const communityPickerUrl = new URL(
  "../app/(presentation-generator)/upload/components/CommunityReferencePicker.tsx",
  import.meta.url,
);
const electronBuildUrl = new URL(
  "../../../electron/scripts/build-nextjs-resources.cjs",
  import.meta.url,
);

test("Linux Electron slides render in-page without Chromium iframe processes", async () => {
  const [source, buildScript] = await Promise.all([
    readFile(smartHtmlSlideUrl, "utf8"),
    readFile(electronBuildUrl, "utf8"),
  ]);

  assert.match(
    buildScript,
    /NEXT_PUBLIC_PRESENTON_ELECTRON_PLATFORM:\s*process\.platform/,
  );
  assert.match(source, /NEXT_PUBLIC_PRESENTON_ELECTRON_PLATFORM === "linux"/);
  assert.match(source, /function LinuxInPageSmartHtmlSlide/);
  assert.match(source, /DOMPurify\.sanitize\(html, SANITIZE_CONFIG\)/);
  assert.match(source, /dangerouslySetInnerHTML=\{\{ __html: sanitizedHtml \}\}/);

  // Other platforms retain the sandboxed iframe renderer.
  assert.match(source, /function IframeSmartHtmlSlide/);
  assert.match(source, /sandbox="allow-scripts"/);
});

test("community HTML cannot execute scripts in the Linux in-page renderer", async () => {
  const sources = await Promise.all([
    readFile(communityPageUrl, "utf8"),
    readFile(communityDialogUrl, "utf8"),
    readFile(communityPickerUrl, "utf8"),
  ]);

  for (const source of sources) {
    assert.match(source, /<SmartHtmlSlide[\s\S]*?executeScripts=\{false\}/);
  }
});
