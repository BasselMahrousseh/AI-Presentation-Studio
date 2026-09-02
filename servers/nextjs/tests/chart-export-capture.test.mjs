import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

async function importChartExportCapture() {
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "chart-export-capture-"));
  const outfile = path.join(tempDirectory, "chart-export-capture.mjs");
  await build({
    absWorkingDir: projectRoot,
    bundle: true,
    entryPoints: ["lib/chart-export-capture.ts"],
    format: "esm",
    outfile,
    platform: "node",
    tsconfig: path.join(projectRoot, "tsconfig.json"),
  });
  return import(pathToFileURL(outfile).href);
}

test("classifies vertical/horizontal/stacked bar variants", async () => {
  const { classifyChartKind } = await importChartExportCapture();

  assert.deepEqual(classifyChartKind("bar", {}, []), { kind: "bar", hasMarkers: false });
  assert.deepEqual(classifyChartKind("bar", { indexAxis: "y" }, []), {
    kind: "horizontal_bar",
    hasMarkers: false,
  });
  assert.deepEqual(
    classifyChartKind("bar", { scales: { y: { stacked: true } } }, []),
    { kind: "stacked_bar", hasMarkers: false },
  );
  assert.deepEqual(
    classifyChartKind(
      "bar",
      { indexAxis: "y", scales: { x: { stacked: true } } },
      [],
    ),
    { kind: "horizontal_stacked_bar", hasMarkers: false },
  );
});

test("distinguishes pie from donut via cutout", async () => {
  const { classifyChartKind } = await importChartExportCapture();

  assert.deepEqual(classifyChartKind("pie", {}, []), { kind: "pie", hasMarkers: false });
  assert.deepEqual(classifyChartKind("doughnut", { cutout: "0%" }, []), {
    kind: "pie",
    hasMarkers: false,
  });
  assert.deepEqual(classifyChartKind("doughnut", { cutout: "58%" }, []), {
    kind: "donut",
    hasMarkers: false,
  });
  assert.deepEqual(classifyChartKind("doughnut", { cutout: 50 }, []), {
    kind: "donut",
    hasMarkers: false,
  });
});

test("distinguishes line from area via dataset fill, and detects markers", async () => {
  const { classifyChartKind } = await importChartExportCapture();

  assert.deepEqual(classifyChartKind("line", {}, [{ pointRadius: 3.5 }]), {
    kind: "line",
    hasMarkers: true,
  });
  assert.deepEqual(classifyChartKind("line", {}, [{ pointRadius: 0 }]), {
    kind: "line",
    hasMarkers: false,
  });
  assert.deepEqual(classifyChartKind("line", {}, [{ fill: true }]), {
    kind: "area",
    hasMarkers: true,
  });
  assert.deepEqual(classifyChartKind("line", {}, [{ fill: "origin" }]), {
    kind: "area",
    hasMarkers: true,
  });
  assert.deepEqual(classifyChartKind("line", {}, [{ fill: false }]), {
    kind: "line",
    hasMarkers: true,
  });
});

test("radar reports markers the same way as line", async () => {
  const { classifyChartKind } = await importChartExportCapture();

  assert.deepEqual(classifyChartKind("radar", {}, [{ pointRadius: 0 }]), {
    kind: "radar",
    hasMarkers: false,
  });
  assert.deepEqual(classifyChartKind("radar", {}, [{}]), {
    kind: "radar",
    hasMarkers: true,
  });
});

test("polar area, scatter, and bubble are always unsupported", async () => {
  const { classifyChartKind } = await importChartExportCapture();

  for (const type of ["polarArea", "scatter", "bubble"]) {
    assert.deepEqual(classifyChartKind(type, {}, []), {
      kind: "unsupported",
      hasMarkers: false,
    });
  }
});

test("unrecognized or missing chart types are unsupported", async () => {
  const { classifyChartKind } = await importChartExportCapture();

  assert.deepEqual(classifyChartKind("someFutureChartType", {}, []), {
    kind: "unsupported",
    hasMarkers: false,
  });
  assert.deepEqual(classifyChartKind(undefined, {}, []), {
    kind: "unsupported",
    hasMarkers: false,
  });
});

test("data labels default to enabled unless explicitly disabled", async () => {
  const { extractDataLabelsEnabled } = await importChartExportCapture();

  assert.equal(extractDataLabelsEnabled({}), true);
  assert.equal(
    extractDataLabelsEnabled({ plugins: { datalabels: { display: true } } }),
    true,
  );
  assert.equal(
    extractDataLabelsEnabled({ plugins: { datalabels: { display: false } } }),
    false,
  );
});

test("font family is read from the first common location that has one", async () => {
  const { extractFontFamily } = await importChartExportCapture();

  assert.equal(extractFontFamily({}), null);
  assert.equal(
    extractFontFamily({ plugins: { title: { font: { family: "Inter" } } } }),
    "Inter",
  );
  assert.equal(
    extractFontFamily({
      plugins: { legend: { labels: { font: { family: "Georgia" } } } },
    }),
    "Georgia",
  );
  assert.equal(
    extractFontFamily({
      plugins: { datalabels: { font: { family: "Roboto" } } },
    }),
    "Roboto",
  );
  assert.equal(
    extractFontFamily({ scales: { x: { ticks: { font: { family: "Arial" } } } } }),
    "Arial",
  );
  assert.equal(
    extractFontFamily({ scales: { y: { ticks: { font: { family: "Verdana" } } } } }),
    "Verdana",
  );
  assert.equal(
    extractFontFamily({
      scales: { r: { pointLabels: { font: { family: "Inter" } } } },
    }),
    "Inter",
  );
});

test("font family ignores Chart.js's own built-in default and prefers a genuinely-customized location", async () => {
  const { extractFontFamily } = await importChartExportCapture();
  const CHARTJS_DEFAULT = "'Helvetica Neue', 'Helvetica', 'Arial', sans-serif";

  // Reproduces the real bug: Chart.js merges its own default font into every
  // plugin's resolved options at runtime (legend/title here), even though
  // this app's charts never customize those - only datalabels/axis ticks
  // are ever actually set to something else (e.g. 'Inter'). The real,
  // customized value must win over the noise default, regardless of object
  // key order.
  assert.equal(
    extractFontFamily({
      plugins: {
        title: { font: { family: CHARTJS_DEFAULT } },
        legend: { labels: { font: { family: CHARTJS_DEFAULT } } },
        datalabels: { font: { family: "Inter" } },
      },
    }),
    "Inter",
  );

  // If nothing anywhere is customized, correctly report "no real font found"
  // rather than reporting Chart.js's own default as if it were meaningful.
  assert.equal(
    extractFontFamily({
      plugins: {
        title: { font: { family: CHARTJS_DEFAULT } },
        legend: { labels: { font: { family: CHARTJS_DEFAULT } } },
      },
    }),
    null,
  );
});

test("tick color is read from axis ticks or radar point labels, ignoring Chart.js's default gray", async () => {
  const { extractTickColor } = await importChartExportCapture();

  assert.equal(extractTickColor({}), null);
  assert.equal(
    extractTickColor({ scales: { x: { ticks: { color: "#AFC3CE" } } } }),
    "#AFC3CE",
  );
  assert.equal(
    extractTickColor({ scales: { y: { ticks: { color: "#8FA8B5" } } } }),
    "#8FA8B5",
  );
  assert.equal(
    extractTickColor({ scales: { r: { pointLabels: { color: "#19303E" } } } }),
    "#19303E",
  );
  assert.equal(
    extractTickColor({ scales: { x: { ticks: { color: "#666" } } } }),
    null,
  );
});

test("data label, legend, and title colors are read, skipping non-string (scriptable) values", async () => {
  const { extractDataLabelColor, extractLegendColor, extractTitleColor } =
    await importChartExportCapture();

  assert.equal(
    extractDataLabelColor({ plugins: { datalabels: { color: "#FFFFFF" } } }),
    "#FFFFFF",
  );
  assert.equal(
    extractDataLabelColor({
      plugins: { datalabels: { color: () => "#FFFFFF" } },
    }),
    null,
  );
  assert.equal(extractDataLabelColor({}), null);

  assert.equal(
    extractLegendColor({
      plugins: { legend: { labels: { color: "#EDEDED" } } },
    }),
    "#EDEDED",
  );
  assert.equal(
    extractTitleColor({ plugins: { title: { color: "#0B1C2C" } } }),
    "#0B1C2C",
  );
});

test("font sizes are read from datalabels, ticks, legend, and title", async () => {
  const {
    extractDataLabelFontSize,
    extractTickFontSize,
    extractTitleFontSize,
    extractLegendPosition,
  } = await importChartExportCapture();

  assert.equal(
    extractDataLabelFontSize({ plugins: { datalabels: { font: { size: 14 } } } }),
    14,
  );
  assert.equal(extractDataLabelFontSize({}), null);

  assert.equal(
    extractTitleFontSize({ plugins: { title: { font: { size: 18 } } } }),
    18,
  );

  assert.equal(
    extractTickFontSize({ scales: { x: { ticks: { font: { size: 13 } } } } }),
    13,
  );
  assert.equal(
    extractTickFontSize({ scales: { y: { ticks: { font: { size: 12 } } } } }),
    12,
  );
  assert.equal(
    extractTickFontSize({ scales: { r: { pointLabels: { font: { size: 11 } } } } }),
    11,
  );
  assert.equal(extractTickFontSize({}), null);

  assert.equal(
    extractLegendPosition({ plugins: { legend: { position: "right" } } }),
    "right",
  );
  assert.equal(extractLegendPosition({}), null);
});

test("tick font size falls back across x, y, and radar point labels", async () => {
  const { extractTickFontSize } = await importChartExportCapture();

  assert.equal(
    extractTickFontSize({
      scales: { x: { ticks: { font: { size: 13 } } }, y: { ticks: { font: { size: 12 } } } },
    }),
    13,
  );
  assert.equal(
    extractTickFontSize({ scales: { y: { ticks: { font: { size: 12 } } } } }),
    12,
  );
});

test("non-numeric, non-finite, and out-of-range font sizes are ignored - but Chart.js's own default of 12 is trusted", async () => {
  const { extractDataLabelFontSize } = await importChartExportCapture();

  const invalid = [
    "14",
    NaN,
    Infinity,
    -Infinity,
    () => 14,
    0,
    -2,
    5000,
  ];
  for (const size of invalid) {
    assert.equal(
      extractDataLabelFontSize({ plugins: { datalabels: { font: { size } } } }),
      null,
      `expected null for ${String(size)}`,
    );
  }

  // Unlike font family and color, there is deliberately no filter for
  // Chart.js's own default font size (12) - 12 is the size Chart.js actually
  // rendered at, not a placeholder meaning "never customized". Filtering it
  // out would discard a correct measurement and reintroduce the bug (native
  // text falling back to PowerPoint's much larger default).
  assert.equal(
    extractDataLabelFontSize({ plugins: { datalabels: { font: { size: 12 } } } }),
    12,
  );
});

test("legend position is only ever one of the four recognized values", async () => {
  const { extractLegendPosition } = await importChartExportCapture();

  for (const position of ["top", "left", "bottom", "right"]) {
    assert.equal(
      extractLegendPosition({ plugins: { legend: { position } } }),
      position,
    );
  }
  assert.equal(
    extractLegendPosition({ plugins: { legend: { position: "chartArea" } } }),
    null,
  );
  assert.equal(
    extractLegendPosition({ plugins: { legend: { position: 42 } } }),
    null,
  );
});

/**
 * Builds an options object whose named property *throws* when read, the way
 * Chart.js's resolved-options proxy does when it evaluates an author-written
 * scriptable option (e.g. `color: (c) => c.dataset.borderColor`) outside a
 * real draw call. This is what silently broke native chart export in
 * production: the throw escaped every extractor, aborted the whole capture,
 * and the entire deck exported as flattened images.
 */
function throwingGetter(target, propertyName, message = "Recursion detected: color->color") {
  return Object.defineProperty(target, propertyName, {
    get() {
      throw new Error(message);
    },
    enumerable: true,
    configurable: true,
  });
}

test("style extractors survive a scriptable option that throws on read", async () => {
  const {
    extractDataLabelColor,
    extractLegendColor,
    extractTitleColor,
    extractTickColor,
    extractFontFamily,
    extractDataLabelsEnabled,
    extractDataLabelFontSize,
    extractTickFontSize,
    extractTitleFontSize,
    extractLegendPosition,
  } = await importChartExportCapture();

  const datalabels = throwingGetter({ font: { family: "Inter" } }, "color");
  assert.equal(extractDataLabelColor({ plugins: { datalabels } }), null);

  // A throwing color must not stop a sibling location from being read.
  assert.equal(
    extractTickColor({
      scales: { x: throwingGetter({}, "ticks"), y: { ticks: { color: "#AFC3CE" } } },
    }),
    "#AFC3CE",
  );

  assert.equal(extractFontFamily({ plugins: { datalabels } }), "Inter");

  assert.equal(
    extractLegendColor({ plugins: { legend: throwingGetter({}, "labels") } }),
    null,
  );
  assert.equal(extractTitleColor({ plugins: throwingGetter({}, "title") }), null);

  // A throwing `display` keeps the documented default-on behaviour rather
  // than silently dropping the chart's data labels.
  assert.equal(
    extractDataLabelsEnabled({
      plugins: { datalabels: throwingGetter({}, "display") },
    }),
    true,
  );

  // A throwing datalabels.font (accessing .color above already consumed the
  // fixture's throwing getter once - build fresh ones per read) degrades to
  // null, and a throwing scale doesn't block its sibling from being read.
  assert.equal(
    extractDataLabelFontSize({
      plugins: { datalabels: throwingGetter({}, "font") },
    }),
    null,
  );
  assert.equal(
    extractTickFontSize({
      scales: {
        x: throwingGetter({}, "ticks"),
        y: { ticks: { font: { size: 13 } } },
      },
    }),
    13,
  );
  assert.equal(
    extractTitleFontSize({ plugins: throwingGetter({}, "title") }),
    null,
  );
  assert.equal(
    extractLegendPosition({ plugins: throwingGetter({}, "legend") }),
    null,
  );
});

test("a chart whose scriptable option throws is still captured, minus that one style", async () => {
  const { classifyAndCaptureChart } = await importChartExportCapture();

  const options = {
    plugins: {
      legend: { display: false, position: "right" },
      datalabels: throwingGetter({ font: { family: "Inter" } }, "color"),
    },
    scales: { y: { ticks: { color: "#0B1F3A", font: { size: 13 } } } },
  };
  const chart = {
    config: { type: "line" },
    data: {
      labels: ["A", "B"],
      datasets: [{ label: "Series", data: [1, 2], borderColor: "#E00600" }],
    },
    options,
  };

  const canvas = {
    getBoundingClientRect: () => ({ left: 40, top: 20, width: 600, height: 300 }),
  };
  const captured = classifyAndCaptureChart(canvas, {
    slideOrderIndex: 3,
    slideContainerEl: {
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 720 }),
    },
    Chart: { getChart: () => chart },
  });

  assert.ok(captured, "chart must still be captured despite the throwing option");
  assert.equal(captured.kind, "line");
  assert.deepEqual(captured.labels, ["A", "B"]);
  assert.deepEqual(captured.datasets[0].data, [1, 2]);
  // The one unreadable style degrades to null; everything else survives.
  assert.equal(captured.dataLabelColor, null);
  assert.equal(captured.tickColor, "#0B1F3A");
  assert.equal(captured.fontFamily, "Inter");
  // New fields land on the captured object too, including the one that has
  // no captured size at all (throwing-datalabels.color doesn't block
  // datalabels.font.size from being read - it's simply absent here).
  assert.equal(captured.dataLabelFontSize, null);
  assert.equal(captured.tickFontSize, 13);
  assert.equal(captured.legend.position, "right");
});
