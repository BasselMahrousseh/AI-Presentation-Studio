/**
 * Applies the font-size/line-height/letter-spacing that Tailwind
 * arbitrary-value text classes (e.g. `text-[64px]`, `leading-[1.04]`,
 * `tracking-[-0.04em]`) would eventually resolve to, as inline styles -
 * written synchronously right after Smart-mode slide HTML is injected,
 * before Tailwind's own JIT engine has had a chance to compile a rule for
 * them.
 *
 * Why this exists: two of this app's Smart-mode slide renderers
 * (SmartHtmlEditor.tsx, and the export page's SmartHtmlPdfSlide) inject raw
 * HTML into the live app DOM and share one whole-page-scoped Tailwind JIT
 * engine (public/vendor/tailwindcss-browser-*.js). That engine recompiles
 * its single shared <style> element asynchronously via a MutationObserver,
 * with no public "wait until done" API. Until a given arbitrary-value class
 * has been compiled at least once anywhere on the page, an element using it
 * renders at Tailwind preflight's un-styled default size - the "heading
 * renders too small" bug, most visible on a slide whose class (e.g.
 * text-[64px] on a title slide, when every other slide only ever uses
 * text-[36px]) is unique in the deck and so has never been compiled before.
 * The sidebar thumbnail never shows this bug because it renders each slide
 * in its own isolated iframe with a fresh Tailwind compile every time.
 *
 * Inline styles always win the cascade over a class selector regardless of
 * source order, so writing the value directly removes the race entirely
 * instead of trying to wait for the JIT more reliably: the correct size is
 * present on first paint. When Tailwind's engine later compiles the
 * identical class, it resolves to the same value, so there is no conflict -
 * this only ever fills a gap, never overrides a genuinely different value.
 */

const ARBITRARY_TEXT_STYLE_PROPERTIES: ReadonlyArray<{
  prefix: string;
  cssProperty: "fontSize" | "lineHeight" | "letterSpacing";
}> = [
  { prefix: "text", cssProperty: "fontSize" },
  { prefix: "leading", cssProperty: "lineHeight" },
  { prefix: "tracking", cssProperty: "letterSpacing" },
];

function arbitraryValueFromClass(token: string, prefix: string): string | null {
  const match = token.match(new RegExp(`^${prefix}-\\[([^\\]]+)\\]$`));
  if (!match) return null;
  // Tailwind's arbitrary-value syntax substitutes underscores for literal
  // spaces inside the brackets - none of these three utilities' values
  // legitimately contain an underscore otherwise (unlike e.g. grid-cols).
  return match[1].replace(/_/g, " ");
}

export function applyArbitraryTextStyles(container: HTMLElement): void {
  const elements: HTMLElement[] = [
    container,
    ...Array.from(container.querySelectorAll<HTMLElement>("[class]")),
  ];
  for (const element of elements) {
    const classAttr = element.getAttribute("class");
    if (!classAttr) continue;
    const tokens = classAttr.split(/\s+/).filter(Boolean);
    for (const token of tokens) {
      for (const { prefix, cssProperty } of ARBITRARY_TEXT_STYLE_PROPERTIES) {
        const value = arbitraryValueFromClass(token, prefix);
        if (value !== null) {
          element.style[cssProperty] = value;
        }
      }
    }
  }
}
