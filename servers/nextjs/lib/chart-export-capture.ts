/**
 * Captures live, fully-rendered Chart.js chart data on the export-only
 * (/pdf-maker) render path, and reports it to FastAPI so a post-export pass
 * (pptx_native_chart_service.py) can swap the flattened chart images the
 * export pipeline always produces for real, editable native PowerPoint
 * charts. Applies uniformly to both content models - TemplateV2's
 * schema-driven chart element and Smart mode's freehand Chart.js code -
 * because by render time both are just a live Chart.js instance on a
 * <canvas>, and Chart.js's own resolved config/data is read directly rather
 * than trying to parse either side's authoring source.
 *
 * Best-effort throughout: any failure here must never affect the export
 * itself, so every entry point below only ever logs and returns/skips.
 */
import {
  loadChartBrowserRuntime,
  type ChartConstructorLike,
} from "@/lib/chart-browser";

export type CapturedChartKind =
  | "bar"
  | "horizontal_bar"
  | "stacked_bar"
  | "horizontal_stacked_bar"
  | "line"
  | "area"
  | "pie"
  | "donut"
  | "radar"
  | "unsupported";

export type CapturedChartDataset = {
  label: string;
  data: number[];
  backgroundColor: string | string[] | null;
  borderColor: string | string[] | null;
};

export type CapturedLegendPosition = "top" | "left" | "bottom" | "right";

export type CapturedChart = {
  slideOrderIndex: number;
  kind: Exclude<CapturedChartKind, "unsupported">;
  hasMarkers: boolean;
  labels: string[];
  datasets: CapturedChartDataset[];
  title: string | null;
  legend: { show: boolean; position: CapturedLegendPosition | null };
  axisTitles: { x: string | null; y: string | null };
  axisTitleColor: string | null;
  boundingBox: { left: number; top: number; width: number; height: number };
  hasDataLabels: boolean;
  fontFamily: string | null;
  tickColor: string | null;
  dataLabelColor: string | null;
  legendColor: string | null;
  titleColor: string | null;
  dataLabelFontSize: number | null;
  tickFontSize: number | null;
  titleFontSize: number | null;
  axisTitleFontSize: number | null;
};

// Both content models' chart canvases match one of these; anything else is
// never waited on or captured (avoids ever blocking on an unrelated canvas).
const CHART_CANVAS_SELECTOR = 'canvas[data-presenton-chart], canvas[id^="chart-"]';

const READY_POLL_INTERVAL_MS = 75;
const READY_POLL_TIMEOUT_MS = 6000;

// A chart reporting "rendered" is not the same as the page having finished
// laying out. Measured on a real export: a chart's own canvas kept its size
// and x-position but slid *down* by up to 24px in the moments after it first
// reported rendered (content above it settling), while the export bundle's
// screenshot - taken later, once the page is fully idle - captured the
// settled position. The captured box and the exported picture then disagreed
// by that drift, scoring IoU 0.86-0.89 against the backend's deliberate
// >=0.90 "fail closed rather than guess" threshold, so those charts silently
// stayed flattened images. So geometry is only read once it stops moving.
// The stable window has to be generous, and `document.fonts` has to be part
// of the check, because of a trap measured on this very page: fonts report
// `status === "loaded"` at the moment charts first render, then a *second*
// wave of font loading starts ~300ms later and finishes ~900ms in, reflowing
// the text above each chart and shifting it. So a single `await
// document.fonts.ready` resolves during that lull and a short "held still for
// 200ms" check concludes settled well before the real move happens.
const LAYOUT_SETTLE_POLL_MS = 100;
const LAYOUT_SETTLE_TIMEOUT_MS = 5000;
const LAYOUT_SETTLE_EPSILON_PX = 0.5;
const LAYOUT_SETTLE_STABLE_ROUNDS = 8;

// Minimal shape of what we read off a live Chart.js instance. Deliberately
// loose (chart-browser.ts's own ChartInstanceLike only exposes
// destroy/update, since that's all its other callers need).
type RawChartInstance = {
  config?: { type?: unknown; data?: unknown; options?: unknown };
  data?: unknown;
  options?: unknown;
};

function readRecord(value: unknown): Record<string, any> {
  return value && typeof value === "object" ? (value as Record<string, any>) : {};
}

/**
 * Reads one value out of Chart.js's *resolved* options and never throws.
 *
 * `chart.options` is not a plain object - it's a lazily-resolving proxy, so
 * merely *reading* a property can execute a scriptable option the slide's
 * author wrote (e.g. `color: (c) => c.dataset.borderColor`, which this app's
 * own Smart-mode generation demonstrably produces). Evaluated outside a real
 * draw call there's no proper resolution context, so such a read can throw
 * ("Recursion detected: color->color", or a TypeError off an undefined
 * context) rather than return a function we could type-check and skip.
 *
 * Every read of resolved options therefore has to be guarded individually,
 * and each guard must wrap the *whole* property chain - an unguarded
 * intermediate hop (`scales.x.ticks`) can throw just as easily as the leaf.
 * That's why the readers below take a getter rather than an already-read
 * value: it keeps the entire chain inside the try.
 */
function safeRead<T>(read: () => T): T | undefined {
  try {
    return read();
  } catch {
    return undefined;
  }
}

function readArray(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
}

function toFiniteNumber(value: unknown): number {
  if (typeof value === "number") return value;
  const record = readRecord(value);
  const candidate = record.y ?? record.value ?? value;
  const parsed = Number(candidate);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function normalizeColorField(value: unknown): string | string[] | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const strings = value.filter((v): v is string => typeof v === "string");
    return strings.length ? strings : null;
  }
  return null;
}

function extractTitleText(options: Record<string, any>): string | null {
  if (safeRead(() => readRecord(readRecord(options.plugins).title).display) === false) {
    return null;
  }
  const text = safeRead(() => readRecord(readRecord(options.plugins).title).text);
  if (typeof text === "string" && text.trim()) return text.trim();
  if (Array.isArray(text)) {
    const joined = text.filter((t) => typeof t === "string").join(" ").trim();
    return joined || null;
  }
  return null;
}

function extractAxisTitle(getScale: () => unknown): string | null {
  const text = safeRead(() => readRecord(readRecord(getScale()).title).text);
  return typeof text === "string" && text.trim() ? text.trim() : null;
}

function extractAxisTitleColor(getScale: () => unknown): string | null {
  const color = safeRead(() => readRecord(readRecord(getScale()).title).color);
  return isRealColor(color) ? color.trim() : null;
}

function extractAxisTitleFontSize(getScale: () => unknown): number | null {
  const size = safeRead(
    () => readRecord(readRecord(readRecord(getScale()).title).font).size,
  );
  return isRealFontSize(size) ? size : null;
}

export function extractDataLabelsEnabled(options: Record<string, any>): boolean {
  // This app's Chart.js generation prompt requires every chart to configure
  // visible datalabels, so default to on unless explicitly disabled -
  // mirrors how `legend.show` is already read above. A `display` that throws
  // (scriptable, see safeRead) reads as undefined here, which keeps that
  // same default-on behaviour rather than silently dropping data labels.
  return (
    safeRead(() => readRecord(readRecord(options.plugins).datalabels).display) !==
    false
  );
}

function fontFamilyOf(getFontHolder: () => unknown): unknown {
  return safeRead(() => readRecord(readRecord(getFontHolder()).font).family);
}

function fontSizeOf(getFontHolder: () => unknown): unknown {
  return safeRead(() => readRecord(readRecord(getFontHolder()).font).size);
}

// Unlike _CHARTJS_DEFAULT_FONT_FAMILY and _CHARTJS_DEFAULT_COLOR below, there
// is deliberately no "filter out Chart.js's own default" step for font size.
// Chart.js merges its default (Chart.defaults.font.size = 12) into every
// resolved plugin/scale just like family and color do - but 12 is the size
// Chart.js actually rendered at, not a placeholder standing in for "never
// customized". Filtering it out would discard a correct measurement and fall
// back to PowerPoint's ~18pt default, which is exactly the bug this capture
// exists to fix. Strict `typeof === "number"` (no coercion): Chart.js's
// documented contract is a number, so a string like "14px" or a scriptable
// function that survived safeRead both correctly read as "not a real size".
function isRealFontSize(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value > 0 &&
    value <= 200
  );
}

// Chart.js's own built-in default (Chart.defaults.font.family in v4). Chart.js
// merges its complete default structure into every nested plugin/scale
// config at runtime, so e.g. `plugins.legend.labels.font.family` always
// resolves to *something* even when this app's charts never touch legend
// styling (legend is usually display:false) - that default value must be
// filtered out, or it wins over a genuinely-customized family found later.
const _CHARTJS_DEFAULT_FONT_FAMILY =
  "'Helvetica Neue', 'Helvetica', 'Arial', sans-serif";

export function extractFontFamily(options: Record<string, any>): string | null {
  // Priority order matters: datalabels and axis ticks are the locations this
  // app's charts actually set a custom font.family on (see
  // CHART_JS_INSTRUCTIONS in generate_smart_presentation.py and
  // CHART_FONT_FAMILY in template-v2-json-to-html.ts); title/legend are
  // checked last since they're rarely styled and mostly just surface Chart.js's
  // own default (filtered out below regardless of where it's found).
  const plugins = readRecord(options.plugins);
  const scales = readRecord(options.scales);
  const candidates = [
    fontFamilyOf(() => plugins.datalabels),
    fontFamilyOf(() => readRecord(scales.x).ticks),
    fontFamilyOf(() => readRecord(scales.y).ticks),
    fontFamilyOf(() => readRecord(scales.r).pointLabels), // radar
    fontFamilyOf(() => plugins.title),
    fontFamilyOf(() => readRecord(plugins.legend).labels),
  ];
  const found = candidates.find(
    (f) =>
      typeof f === "string" &&
      f.trim() &&
      f.trim() !== _CHARTJS_DEFAULT_FONT_FAMILY,
  );
  return typeof found === "string" ? found.trim() : null;
}

export function extractTickFontSize(options: Record<string, any>): number | null {
  // Same "one representative value covers both axes plus radar" reasoning as
  // extractTickColor: this app's charts use one consistent axis-label size,
  // and axis titles in this app's own generators track tick size to within a
  // couple of px, so this single value also backs extractAxisTitleFontSize's
  // fallback in classifyAndCaptureChart below.
  const scales = readRecord(options.scales);
  const candidates = [
    fontSizeOf(() => readRecord(scales.x).ticks),
    fontSizeOf(() => readRecord(scales.y).ticks),
    fontSizeOf(() => readRecord(scales.r).pointLabels),
  ];
  const found = candidates.find(isRealFontSize);
  return typeof found === "number" ? found : null;
}

export function extractDataLabelFontSize(options: Record<string, any>): number | null {
  const size = fontSizeOf(() => readRecord(options.plugins).datalabels);
  return isRealFontSize(size) ? size : null;
}

export function extractTitleFontSize(options: Record<string, any>): number | null {
  const size = fontSizeOf(() => readRecord(options.plugins).title);
  return isRealFontSize(size) ? size : null;
}

const _LEGEND_POSITIONS: ReadonlySet<string> = new Set([
  "top",
  "left",
  "bottom",
  "right",
]);

export function extractLegendPosition(
  options: Record<string, any>,
): CapturedLegendPosition | null {
  const position = safeRead(() => readRecord(options.plugins).legend?.position);
  return typeof position === "string" && _LEGEND_POSITIONS.has(position)
    ? (position as CapturedLegendPosition)
    : null;
}

function colorOf(getColorHolder: () => unknown): unknown {
  return safeRead(() => readRecord(getColorHolder()).color);
}

// Chart.js's own built-in default (Chart.defaults.color in v4) - the same
// "resolved runtime options always have *something* here, even when this
// app's charts never customized it" trap as _CHARTJS_DEFAULT_FONT_FAMILY
// above. Every one of this app's actual chart configs explicitly sets tick/
// datalabel colors (dark text on a light card, or light text on a dark
// card, per the deck's own palette), so this filter mostly guards against
// an unusual chart that genuinely never touched color.
const _CHARTJS_DEFAULT_COLOR = "#666";

function isRealColor(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.trim().toLowerCase() !== _CHARTJS_DEFAULT_COLOR
  );
}

export function extractTickColor(options: Record<string, any>): string | null {
  // One representative color for axis tick/category labels - this app's
  // charts consistently use a single light-on-dark or dark-on-light color
  // for all of a chart's axis text, so the first real value found covers
  // both axes (and radar's point labels).
  const scales = readRecord(options.scales);
  const candidates = [
    colorOf(() => readRecord(scales.x).ticks),
    colorOf(() => readRecord(scales.y).ticks),
    colorOf(() => readRecord(scales.r).pointLabels),
  ];
  const found = candidates.find(isRealColor);
  return typeof found === "string" ? found.trim() : null;
}

export function extractDataLabelColor(options: Record<string, any>): string | null {
  // A scriptable (function) color, e.g. `color: ctx => ctx.dataset.borderColor`,
  // can't be read generically without evaluating arbitrary LLM-authored code -
  // skip it rather than guess. Note the *read itself* is what has to be
  // guarded (see safeRead): on Chart.js's resolved-options proxy, touching a
  // scriptable property executes it and can throw outright, so it never even
  // reaches isRealColor's typeof check.
  const color = colorOf(() => readRecord(options.plugins).datalabels);
  return isRealColor(color) ? color.trim() : null;
}

export function extractLegendColor(options: Record<string, any>): string | null {
  const color = colorOf(() => readRecord(readRecord(options.plugins).legend).labels);
  return isRealColor(color) ? color.trim() : null;
}

export function extractTitleColor(options: Record<string, any>): string | null {
  const color = colorOf(() => readRecord(options.plugins).title);
  return isRealColor(color) ? color.trim() : null;
}

function hasAnyMarkers(datasets: any[]): boolean {
  // Chart.js default pointRadius is >0 (markers on); a dataset only loses
  // its markers if pointRadius is explicitly set to 0 (or negative).
  return !datasets.every((d) => {
    const radius = d?.pointRadius;
    return typeof radius === "number" && radius <= 0;
  });
}

function isStackedScales(scales: unknown): boolean {
  const record = readRecord(scales);
  return Boolean(readRecord(record.x).stacked) || Boolean(readRecord(record.y).stacked);
}

export function classifyChartKind(
  rawType: unknown,
  options: Record<string, any>,
  datasets: any[],
): { kind: CapturedChartKind; hasMarkers: boolean } {
  const type = typeof rawType === "string" ? rawType : "";

  if (type === "polarArea" || type === "scatter" || type === "bubble") {
    return { kind: "unsupported", hasMarkers: false };
  }

  if (type === "pie" || type === "doughnut") {
    const cutout = options.cutout;
    const cutoutNumber =
      typeof cutout === "number"
        ? cutout
        : typeof cutout === "string"
          ? parseFloat(cutout)
          : 0;
    const isPie = type === "pie" || !Number.isFinite(cutoutNumber) || cutoutNumber <= 0;
    return { kind: isPie ? "pie" : "donut", hasMarkers: false };
  }

  if (type === "radar") {
    return { kind: "radar", hasMarkers: hasAnyMarkers(datasets) };
  }

  if (type === "line") {
    const isArea = datasets.some((d) => d?.fill === true || (d?.fill != null && d.fill !== false));
    return { kind: isArea ? "area" : "line", hasMarkers: hasAnyMarkers(datasets) };
  }

  if (type === "bar") {
    const horizontal = options.indexAxis === "y";
    const stacked = isStackedScales(options.scales);
    if (horizontal && stacked) return { kind: "horizontal_stacked_bar", hasMarkers: false };
    if (horizontal) return { kind: "horizontal_bar", hasMarkers: false };
    if (stacked) return { kind: "stacked_bar", hasMarkers: false };
    return { kind: "bar", hasMarkers: false };
  }

  return { kind: "unsupported", hasMarkers: false };
}

export function classifyAndCaptureChart(
  canvas: HTMLCanvasElement,
  ctx: {
    slideOrderIndex: number;
    slideContainerEl: Element;
    Chart: ChartConstructorLike;
  },
): CapturedChart | null {
  const chart = ctx.Chart.getChart(canvas) as unknown as RawChartInstance | undefined;
  if (!chart) return null;

  const config = readRecord(chart.config);
  const data = readRecord(safeRead(() => chart.data) ?? config.data);
  const options = readRecord(
    safeRead(() => (chart as any).options) ?? config.options,
  );
  const rawType = config.type ?? safeRead(() => (chart as any).type);

  const labels = readArray(data.labels).map((label) => String(label));
  const rawDatasets = readArray(data.datasets);
  if (!labels.length || !rawDatasets.length) return null;

  const { kind, hasMarkers } = classifyChartKind(rawType, options, rawDatasets);
  if (kind === "unsupported") return null;

  const datasets: CapturedChartDataset[] = rawDatasets.map((dataset) => {
    const values = readArray(dataset?.data).map(toFiniteNumber);
    return {
      label: typeof dataset?.label === "string" && dataset.label ? dataset.label : "Series",
      data: values,
      backgroundColor: normalizeColorField(dataset?.backgroundColor),
      borderColor: normalizeColorField(dataset?.borderColor),
    };
  });

  const hasValidData = datasets.every(
    (dataset) => dataset.data.length === labels.length && dataset.data.every(Number.isFinite),
  );
  if (!hasValidData) return null;

  const canvasRect = canvas.getBoundingClientRect();
  const slideRect = ctx.slideContainerEl.getBoundingClientRect();
  const boundingBox = {
    left: canvasRect.left - slideRect.left,
    top: canvasRect.top - slideRect.top,
    width: canvasRect.width,
    height: canvasRect.height,
  };
  if (boundingBox.width <= 0 || boundingBox.height <= 0) return null;

  const scales = readRecord(options.scales);
  const isAxisChart = !(kind === "pie" || kind === "donut" || kind === "radar");
  const horizontal = kind === "horizontal_bar" || kind === "horizontal_stacked_bar";

  return {
    slideOrderIndex: ctx.slideOrderIndex,
    kind,
    hasMarkers,
    labels,
    datasets,
    title: extractTitleText(options),
    legend: {
      show:
        safeRead(() => readRecord(options.plugins).legend?.display) !== false,
      position: extractLegendPosition(options),
    },
    axisTitles: isAxisChart
      ? {
          x: extractAxisTitle(() => (horizontal ? scales.y : scales.x)),
          y: extractAxisTitle(() => (horizontal ? scales.x : scales.y)),
        }
      : { x: null, y: null },
    axisTitleColor: isAxisChart
      ? (extractAxisTitleColor(() => (horizontal ? scales.y : scales.x)) ??
        extractAxisTitleColor(() => (horizontal ? scales.x : scales.y)))
      : null,
    boundingBox,
    hasDataLabels: extractDataLabelsEnabled(options),
    fontFamily: extractFontFamily(options),
    tickColor: extractTickColor(options),
    dataLabelColor: extractDataLabelColor(options),
    legendColor: extractLegendColor(options),
    titleColor: extractTitleColor(options),
    dataLabelFontSize: extractDataLabelFontSize(options),
    tickFontSize: extractTickFontSize(options),
    titleFontSize: extractTitleFontSize(options),
    axisTitleFontSize: isAxisChart
      ? (extractAxisTitleFontSize(() => (horizontal ? scales.y : scales.x)) ??
        extractAxisTitleFontSize(() => (horizontal ? scales.x : scales.y)) ??
        extractTickFontSize(options))
      : null,
  };
}

function isChartCanvasRendered(canvas: HTMLCanvasElement): boolean {
  return canvas.dataset.presentonChartRendered === "true";
}

async function waitForChartsToRender(): Promise<void> {
  const start = Date.now();
  for (;;) {
    const canvases = Array.from(
      document.querySelectorAll<HTMLCanvasElement>(CHART_CANVAS_SELECTOR),
    );
    if (canvases.length === 0 || canvases.every(isChartCanvasRendered)) return;
    if (Date.now() - start > READY_POLL_TIMEOUT_MS) return;
    await new Promise((resolve) => setTimeout(resolve, READY_POLL_INTERVAL_MS));
  }
}

type ChartRect = { left: number; top: number; width: number; height: number };

function readChartRects(): ChartRect[] {
  return Array.from(
    document.querySelectorAll<HTMLCanvasElement>(CHART_CANVAS_SELECTOR),
  ).map((canvas) => {
    const rect = canvas.getBoundingClientRect();
    return {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    };
  });
}

function chartRectsAreStable(before: ChartRect[], after: ChartRect[]): boolean {
  if (before.length !== after.length) return false;
  return before.every((rect, index) => {
    const next = after[index];
    return (
      Math.abs(rect.left - next.left) <= LAYOUT_SETTLE_EPSILON_PX &&
      Math.abs(rect.top - next.top) <= LAYOUT_SETTLE_EPSILON_PX &&
      Math.abs(rect.width - next.width) <= LAYOUT_SETTLE_EPSILON_PX &&
      Math.abs(rect.height - next.height) <= LAYOUT_SETTLE_EPSILON_PX
    );
  });
}

/**
 * Blocks until every chart's on-page geometry has held still across a couple
 * of consecutive polls, so the boxes reported to the backend match where the
 * export bundle will actually screenshot them (see LAYOUT_SETTLE_* above).
 * Bounded by a timeout - on expiry it returns and lets capture proceed with
 * whatever the current geometry is, since a slightly-off box that fails the
 * backend's IoU check is no worse than today's flattened image, whereas
 * waiting forever would lose the capture entirely.
 *
 * Deliberately uses only timers and layout reads: no fetch/XHR, which would
 * risk stalling the export's own `waitUntil: "networkidle0"` navigation.
 */
async function waitForStableChartLayout(): Promise<void> {
  const start = Date.now();
  let previous = readChartRects();
  let stableRounds = 0;

  while (Date.now() - start <= LAYOUT_SETTLE_TIMEOUT_MS) {
    await new Promise((resolve) => setTimeout(resolve, LAYOUT_SETTLE_POLL_MS));

    const current = readChartRects();
    // Fonts still arriving means more reflow is coming, no matter how still
    // the boxes look right now - never count those polls as settled.
    const fontsBusy = safeRead(() => document.fonts?.status) === "loading";
    stableRounds =
      !fontsBusy && chartRectsAreStable(previous, current) ? stableRounds + 1 : 0;
    previous = current;

    if (stableRounds >= LAYOUT_SETTLE_STABLE_ROUNDS) return;
  }
}

export async function captureAllChartsOnPage(opts: {
  token: string;
  presentationId: string;
  reportUrl: string;
}): Promise<void> {
  try {
    await waitForChartsToRender();
    await waitForStableChartLayout();

    const canvases = Array.from(
      document.querySelectorAll<HTMLCanvasElement>(CHART_CANVAS_SELECTOR),
    );
    if (!canvases.length) return;

    const runtime = await loadChartBrowserRuntime().catch(() => null);
    if (!runtime) return;

    const slideContainers = Array.from(
      document.querySelectorAll<HTMLElement>("#presentation-slides-wrapper .main-slide"),
    );

    const charts: CapturedChart[] = [];
    canvases.forEach((canvas) => {
      // Isolated per chart on purpose. Reading a chart's resolved options can
      // throw on an author-written scriptable option (see safeRead), and this
      // loop used to sit inside one shared try/catch - so a single bad chart
      // anywhere in the deck aborted the whole capture and discarded every
      // good chart already collected, silently exporting the entire deck as
      // flattened images. Now one bad chart costs only that chart.
      try {
        const slideContainerEl = canvas.closest<HTMLElement>(".main-slide");
        if (!slideContainerEl) return;
        const slideOrderIndex = slideContainers.indexOf(slideContainerEl);
        if (slideOrderIndex < 0) return;

        const captured = classifyAndCaptureChart(canvas, {
          slideOrderIndex,
          slideContainerEl,
          Chart: runtime.Chart,
        });
        if (captured) charts.push(captured);
      } catch (error) {
        console.warn(
          `[chart-export-capture] Skipped one chart (${canvas.id || "unnamed"})`,
          error,
        );
      }
    });

    if (!charts.length) return;

    const payload = JSON.stringify({
      token: opts.token,
      presentation_id: opts.presentationId,
      charts,
    });

    // Deliberately navigator.sendBeacon(), not fetch(): the export tool
    // navigates here with page.goto(url, {waitUntil: "networkidle0"}), and
    // ANY same-origin fetch()/XHR fired while that wait is still pending -
    // even one that completes quickly and successfully, even with no
    // `keepalive` option - was empirically confirmed (via direct reproduction
    // and a debug bisection) to make Puppeteer's network-idle tracking never
    // settle, hanging the whole export until its 120s navigation timeout.
    // sendBeacon is purpose-built for "notify the server without disrupting
    // page lifecycle" and sidesteps this. It can't carry a custom
    // x-export-cookie header, but /export/chart-capture doesn't require
    // auth (best-effort endpoint), so that's not a functional loss.
    const sent =
      typeof navigator !== "undefined" && "sendBeacon" in navigator
        ? navigator.sendBeacon(
            opts.reportUrl,
            new Blob([payload], { type: "application/json" }),
          )
        : false;
    if (!sent) {
      // sendBeacon unavailable/failed to queue (e.g. payload too large) -
      // fall back to a normal fetch; worst case this reintroduces the
      // networkidle0 risk above, but that's better than losing the report
      // entirely.
      await fetch(opts.reportUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
      }).catch(() => undefined);
    }
  } catch (error) {
    console.warn("[chart-export-capture] Skipped native chart capture", error);
  }
}
