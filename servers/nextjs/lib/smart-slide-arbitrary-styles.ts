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

/**
 * Same race, same fix, for `grid-cols-[...]` - a separate function rather
 * than folding into applyArbitraryTextStyles above, so the working,
 * independently-tested font-size fix's name and behavior stay untouched.
 *
 * `grid-cols-[...]` is not a text property, but it can go through the exact
 * same async-compile race described above, and it is a far more common
 * pattern in generated Smart slides than any single arbitrary text size
 * (measured: 97 distinct arbitrary grid-cols values across every slide
 * currently stored in this app's own database, one of the most-used
 * arbitrary-value utilities in generated HTML). Kept as a real defensive fix
 * for that race even though it turned out NOT to be the cause of the
 * "Desktop"/"55%" wrapping bug this was originally written to chase (see
 * applyGridItemMinWidthGuard below for the real cause and fix, confirmed by
 * live reproduction) - a slide whose grid-cols split briefly renders at
 * Tailwind's un-styled default (a single collapsed track) until the shared
 * engine catches up is still a real, if rarer, way to get a badly squeezed
 * column, independent of the min-content issue below.
 *
 * `grid-rows-[...]` and arbitrary `gap-[...]` are deliberately not handled:
 * neither appears anywhere in this app's own generated-slide database (the
 * model never produces them), so adding them now would be speculative code
 * for a pattern with no evidence it occurs - if that changes, extend
 * GRID_TEMPLATE_STYLE_PROPERTIES below the same way.
 */
const GRID_TEMPLATE_STYLE_PROPERTIES: ReadonlyArray<{
  prefix: string;
  cssProperty: "gridTemplateColumns";
}> = [{ prefix: "grid-cols", cssProperty: "gridTemplateColumns" }];

export function applyArbitraryGridStyles(container: HTMLElement): void {
  const elements: HTMLElement[] = [
    container,
    ...Array.from(container.querySelectorAll<HTMLElement>("[class]")),
  ];
  for (const element of elements) {
    const classAttr = element.getAttribute("class");
    if (!classAttr) continue;
    const tokens = classAttr.split(/\s+/).filter(Boolean);
    for (const token of tokens) {
      for (const { prefix, cssProperty } of GRID_TEMPLATE_STYLE_PROPERTIES) {
        const value = arbitraryValueFromClass(token, prefix);
        if (value !== null) {
          element.style[cssProperty] = value;
        }
      }
    }
  }
}

/**
 * Forces `min-width: 0` on every direct child of a `flex`/`grid` container
 * in the injected slide, unless that child already declares its own
 * `min-w-*` class (an explicit choice this never overrides).
 *
 * This is the actual fix for a real, live bug, found and confirmed by
 * driving the running app with Puppeteer against a real reported slide (not
 * a class-analysis guess): a device-mix donut slide's "55%"/"Desktop" stat
 * labels were wrapping mid-word - not intermittently, on every single load,
 * which ruled out a Tailwind-compile race (see applyArbitraryGridStyles
 * above for that separate, real-but-different race). Inspecting the live,
 * fully-resolved computed styles showed the slide's own
 * `grid-cols-[0.38fr_0.62fr]` text/chart split WAS correctly applied
 * (166px/694px, not 0), yet the text column was still far narrower than its
 * 0.38fr share should give it (~420px expected). Root cause: by the CSS
 * Grid/Flexbox spec, a grid or flex item's `min-width` defaults to `auto` -
 * its own content's min-content size - and that default takes priority over
 * a `fr` track's proportional share. The chart panel's `<canvas
 * width="660">` has a fixed intrinsic width, so its min-content size
 * (~694px, canvas + padding) became a hard floor on the 0.62fr column,
 * stealing space from the 0.38fr text column instead of the two splitting
 * 38/62 as authored. Confirmed directly by forcing `min-width: 0` on that
 * one chart panel in the live page and re-measuring: the columns
 * re-balanced to their intended ~368px/600px split and every wrapped label
 * (verified via getBoundingClientRect().height, roughly double a normal
 * single line before the fix) dropped back to a normal single-line height.
 *
 * This app's own Smart-generation prompt already tells the model to "Add
 * `min-w-0` to constrained columns" for exactly this reason (
 * SMART_OVERFLOW_PREVENTION_PROMPT, generate_smart_presentation.py) - this
 * function makes that guidance actually true regardless of whether a given
 * generation followed it, the same way this file's other functions make
 * arbitrary-value classes correct regardless of JIT compile timing. Applied
 * to every flex/grid container's children, not only ones holding a chart:
 * the failure mode - a child whose own content has a fixed or otherwise
 * large intrinsic width forcing its track/flex-basis wider than intended -
 * is generic, not chart-specific, and `min-width: 0` is a no-op for any
 * child that was never being squeezed in the first place, so applying it
 * broadly costs nothing for the common case and only ever helps the
 * uncommon one.
 *
 * Deliberately width-only (no matching min-height:0 for flex-col/grid rows):
 * a row that grows too tall to fit is already caught by the real-render
 * canvas-overflow check in generate_smart_presentation.py, which measures
 * final painted height directly - but that check has no visibility into a
 * column being squeezed narrower than intended, since squeezing never pushes
 * content past y=720. This fix and that check cover two orthogonal failure
 * axes; this one closes the gap the other structurally cannot see.
 */
function containerIsFlexOrGrid(classAttr: string): boolean {
  return /(^|\s)(flex|grid)(\s|$)/.test(classAttr);
}

// A token counts as an explicit, different choice this must never override
// only if it's a min-w-* class OTHER than min-w-0 itself (min-w-[200px],
// min-w-full, min-w-fit, ...). A child that already declares min-w-0 should
// still get the inline style written, for the same reason every other fix
// in this file does: the class alone doesn't guarantee the shared Tailwind
// engine has compiled it yet, and writing the (here, identical) value
// inline costs nothing while removing that last dependency on JIT timing.
function isExplicitNonZeroMinWidthClass(token: string): boolean {
  return token.startsWith("min-w-") && token !== "min-w-0";
}

export function applyGridItemMinWidthGuard(container: HTMLElement): void {
  const containers: HTMLElement[] = [
    container,
    ...Array.from(container.querySelectorAll<HTMLElement>("[class]")),
  ];
  for (const element of containers) {
    const classAttr = element.getAttribute("class");
    if (!classAttr || !containerIsFlexOrGrid(classAttr)) continue;
    // `.children` (unlike `.childNodes`) only ever yields Element nodes, so
    // this cast is safe; done as a cast rather than an `instanceof
    // HTMLElement` filter to match this file's existing style (no runtime
    // DOM-class checks elsewhere) and to keep this testable against the
    // plain-object DOM stand-ins this file's own tests use (no real DOM in
    // the Node test environment).
    for (const child of Array.from(element.children) as HTMLElement[]) {
      const childClassAttr = child.getAttribute("class") ?? "";
      const childTokens = childClassAttr.split(/\s+/).filter(Boolean);
      if (childTokens.some(isExplicitNonZeroMinWidthClass)) continue;
      child.style.minWidth = "0px";
    }
  }
}
