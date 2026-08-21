import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sharedDialogUrl = new URL("../components/ui/dialog.tsx", import.meta.url);
const directDialogUrls = [
  new URL("../components/slide-editor/images/ImagePickerModal.tsx", import.meta.url),
  new URL("../components/slide-editor/images/IconsEditor.tsx", import.meta.url),
  new URL(
    "../app/(presentation-generator)/presentation/components/Modal.tsx",
    import.meta.url,
  ),
];

test("centered dialogs neutralize Tailwind 4 individual translate utilities", async () => {
  const sharedDialog = await readFile(sharedDialogUrl, "utf8");

  assert.match(sharedDialog, /style=\{\{ translate: "none", \.\.\.style \}\}/);
  assert.match(sharedDialog, /translate-x-\[-50%\]/);
  assert.match(sharedDialog, /translate-y-\[-50%\]/);

  for (const dialogUrl of directDialogUrls) {
    const source = await readFile(dialogUrl, "utf8");
    assert.match(source, /style=\{\{ translate: "none" \}\}/);
  }
});
