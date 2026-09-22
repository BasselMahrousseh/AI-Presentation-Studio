import { resolveBackendAssetUrl } from "@/utils/api";

/**
 * Smart slides store raw HTML that references backend-served files by root-relative path
 * (`/app_data/images/...`, `/static/...`, and the e& template artwork under `/smart-templates/...`). That only resolves when the app shares an origin with the
 * backend. A host that reaches the backend through a proxy prefix (the Workspace UI) needs those
 * paths rewritten when the HTML is displayed, and restored before it is saved so the stored slide
 * never contains a host-specific prefix.
 */
const ASSET_PATH = String.raw`\/(?:app_data|static|smart-templates)\/[^"'\s)&<>]*`;
const ASSET_ATTRIBUTE = new RegExp(
  String.raw`(\b(?:src|poster|data-src)\s*=\s*)(["'])(${ASSET_PATH})\2`,
  "gi"
);
const ASSET_CSS_URL = new RegExp(
  String.raw`(url\(\s*(?:&quot;|["'])?)(${ASSET_PATH})`,
  "gi"
);

/** The prefix `resolveBackendAssetUrl` puts in front of a backend path ("" when same-origin). */
function backendAssetPrefix(): string {
  const probe = "/app_data/__prefix_probe__";
  const resolved = resolveBackendAssetUrl(probe);
  const at = resolved.indexOf(probe);
  return at > 0 ? resolved.slice(0, at) : "";
}

export function resolveSmartHtmlAssets(html: string): string {
  if (!html || !backendAssetPrefix()) return html;
  return html
    .replace(ASSET_ATTRIBUTE, (_m, lead: string, quote: string, path: string) =>
      `${lead}${quote}${resolveBackendAssetUrl(path)}${quote}`
    )
    .replace(ASSET_CSS_URL, (_m, lead: string, path: string) =>
      `${lead}${resolveBackendAssetUrl(path)}`
    );
}

export function restoreSmartHtmlAssets(html: string): string {
  const prefix = backendAssetPrefix();
  if (!html || !prefix) return html;
  return html.split(`${prefix}/app_data/`).join("/app_data/").split(`${prefix}/static/`).join("/static/")
    .split(`${prefix}/smart-templates/`).join("/smart-templates/");
}
