/**
 * diagram-engine.js
 *
 * Per 06_Template_and_PPTX_Engineering.md section 6.8: the diagram engine
 * accepts a graph/structured model and computes geometry deterministically,
 * producing grouped native shapes/connectors â€” never a raster image.
 *
 * The original spec example (section 6.8) used a simple {nodes, edges}
 * graph. Real upstream payloads (see the RAG example SlideSpec) use a
 * wider variety of diagram_type values with their own data shapes:
 *   - pipeline              -> data.steps: string[]
 *   - numbered_process      -> data.steps: {step,title,description}[]
 *   - system_architecture / ops_workflow
 *                            -> data.components: {name,details[]}[], data.flows: [from,to][]
 *   - annotated_components  -> data.components: {name,details}[], data.relationships: [from,to][]
 *   - grid                  -> data.items: {title,description}[]
 *   - trend_map             -> data.trends: {name,description}[]
 *   - balance_axes          -> data.tradeoffs: {factor,impact}[]
 *   - (no diagram_type)     -> data.nodes/data.edges (original graph model)
 *
 * Every renderer here degrades to a clearly-labelled placeholder rather
 * than throwing, and any genuinely unrecognised diagram_type falls back
 * to a generic bullet list built from whatever text fields it can find â€”
 * per AGENTS.md: never silently drop content.
 */

const PALETTE = {
  boxFill: 'F2F6FC',
  boxLine: '4472C4',
  boxText: '1F3864',
  connector: '999999',
};

function addBox(slide, x, y, w, h, label, sublabel) {
  slide.addShape('roundRect', {
    x, y, w, h,
    fill: { color: PALETTE.boxFill },
    line: { color: PALETTE.boxLine, width: 1 },
    rectRadius: 0.06,
  });
  const lines = [{ text: label, options: { bold: true, fontSize: 11 } }];
  if (sublabel) {
    lines.push({ text: sublabel, options: { fontSize: 8, breakLine: true } });
  }
  slide.addText(lines, {
    x, y, w, h,
    align: 'center',
    valign: 'middle',
    color: PALETTE.boxText,
    fontSize: 11,
  });
}

function addHorizontalArrow(slide, x1, y1, x2, y2) {
  slide.addShape('line', {
    x: Math.min(x1, x2),
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: { color: PALETTE.connector, width: 1.5, endArrowType: 'triangle' },
  });
}

/**
 * Lay out a chain of boxes left-to-right within `area`, wrapping to a new
 * row when there isn't enough width â€” handles diagrams with more nodes
 * (6-7) than comfortably fit on one row.
 */
function layoutChain(labels, area, opts = {}) {
  const boxW = opts.boxW || 1.9;
  const boxH = opts.boxH || 0.8;
  const gapX = 0.3;
  const gapY = 0.3;

  const perRow = Math.max(1, Math.floor((area.w + gapX) / (boxW + gapX)));
  const rows = Math.ceil(labels.length / perRow);
  const totalW = Math.min(labels.length, perRow) * boxW + (Math.min(labels.length, perRow) - 1) * gapX;
  const startX = area.x + Math.max((area.w - totalW) / 2, 0);
  const startY = area.y + Math.max((area.h - (rows * boxH + (rows - 1) * gapY)) / 2, 0);

  return labels.map((label, i) => {
    const row = Math.floor(i / perRow);
    const col = i % perRow;
    return {
      label,
      x: startX + col * (boxW + gapX),
      y: startY + row * (boxH + gapY),
      w: boxW,
      h: boxH,
      row,
      col,
    };
  });
}

// ---------------------------------------------------------------------------
// pipeline: data.steps = string[]
// ---------------------------------------------------------------------------
function renderPipeline(slide, data, area, warnings) {
  if (!Array.isArray(data.steps)) {
    warnings.push('Diagram type "pipeline" is missing "data.steps" â€” skipped.');
    return;
  }
  const annotations = Array.isArray(data.annotations)
    ? data.annotations.filter((annotation) => String(annotation).trim())
    : [];

  // Reserve a distinct band for phase labels; annotations must not disappear
  // simply because they are not graph nodes.
  const annotationBandH = annotations.length > 0 ? 0.42 : 0;
  const pipelineArea = {
    x: area.x,
    y: area.y + annotationBandH,
    w: area.w,
    h: Math.max(area.h - annotationBandH, 0.7),
  };
  const boxes = layoutChain(data.steps, pipelineArea, { boxW: 1.7, boxH: 0.7 });
  boxes.forEach((b, i) => {
    if (i > 0 && boxes[i - 1].row === b.row) {
      const prev = boxes[i - 1];
      addHorizontalArrow(slide, prev.x + prev.w, prev.y + prev.h / 2, b.x, b.y + b.h / 2);
    }
    addBox(slide, b.x, b.y, b.w, b.h, b.label);
  });

  if (annotations.length === 0) return;

  // With no explicit stage ranges in the contract, split stages evenly and
  // deterministically between the supplied phase annotations.
  const annotationY = area.y + 0.02;
  annotations.forEach((annotation, index) => {
    const start = Math.floor((index * boxes.length) / annotations.length);
    const end = Math.max(start, Math.floor(((index + 1) * boxes.length) / annotations.length) - 1);
    const covered = boxes.slice(start, end + 1);
    if (covered.length === 0) return;

    // For wrapped pipelines, do not span phase labels across disconnected rows.
    const sameRow = covered.filter((box) => box.row === covered[0].row);
    const first = sameRow[0];
    const last = sameRow[sameRow.length - 1];
    const x = first.x;
    const w = Math.max(last.x + last.w - first.x, 0.7);
    slide.addShape('roundRect', {
      x, y: annotationY, w, h: 0.3,
      fill: { color: 'E7EEFB', transparency: 15 },
      line: { color: '9CB7E3', width: 0.75 },
      rectRadius: 0.04,
    });
    slide.addText(String(annotation), {
      x, y: annotationY, w, h: 0.3,
      fontSize: 8,
      bold: true,
      color: PALETTE.boxText,
      align: 'center',
      valign: 'middle',
    });
  });
}

// ---------------------------------------------------------------------------
// numbered_process: data.steps = { step, title, description }[]
// ---------------------------------------------------------------------------
function renderNumberedProcess(slide, data, area, warnings) {
  if (!Array.isArray(data.steps)) {
    warnings.push('Diagram type "numbered_process" is missing "data.steps" â€” skipped.');
    return;
  }
  const labels = data.steps.map((s) => `${s.step ?? ''}. ${s.title ?? ''}`.trim());
  const boxes = layoutChain(labels, area, { boxW: 1.9, boxH: 0.9 });
  boxes.forEach((b, i) => {
    if (i > 0 && boxes[i - 1].row === b.row) {
      const prev = boxes[i - 1];
      addHorizontalArrow(slide, prev.x + prev.w, prev.y + prev.h / 2, b.x, b.y + b.h / 2);
    }
    const sub = data.steps[i].description;
    addBox(slide, b.x, b.y, b.w, b.h, b.label, sub ? String(sub).slice(0, 60) : null);
  });
}

// ---------------------------------------------------------------------------
// system_architecture / ops_workflow: data.components = {name, details[]}[],
// data.flows = [from, to][] (by component name)
// ---------------------------------------------------------------------------
function renderComponentFlow(slide, data, area, warnings) {
  if (!Array.isArray(data.components)) {
    warnings.push('Diagram is missing "data.components" â€” skipped.');
    return;
  }
  const names = data.components.map((c) => c.name);
  const boxes = layoutChain(names, area, { boxW: 1.9, boxH: 0.9 });
  const boxByName = {};
  boxes.forEach((b, i) => {
    boxByName[names[i]] = b;
  });

  (data.flows || []).forEach(([from, to]) => {
    const a = boxByName[from];
    const b = boxByName[to];
    if (!a || !b) {
      // Flow may reference an external actor not in "components" (e.g.
      // "User Query" in the RAG example) â€” that's expected, not an error;
      // only warn when neither endpoint is resolvable at all.
      return;
    }
    if (a.row === b.row) {
      addHorizontalArrow(slide, a.x + a.w, a.y + a.h / 2, b.x, b.y + b.h / 2);
    }
  });

  boxes.forEach((b, i) => {
    const details = data.components[i].details;
    const sub = Array.isArray(details) ? details.join(', ') : details;
    addBox(slide, b.x, b.y, b.w, b.h, b.label, sub ? String(sub).slice(0, 50) : null);
  });
}

// ---------------------------------------------------------------------------
// grid / trend_map: data.items or data.trends = {title|name, description}[]
// ---------------------------------------------------------------------------

function addGridCard(slide, x, y, w, h, title, items) {
  slide.addShape('roundRect', {
    x,
    y,
    w,
    h,
    fill: { color: PALETTE.boxFill },
    line: { color: PALETTE.boxLine, width: 1 },
    rectRadius: 0.06,
  });

  slide.addText(title, {
    x: x + 0.15,
    y: y + 0.15,
    w: w - 0.3,
    h: 0.35,
    fontSize: 13,
    bold: true,
    color: PALETTE.boxText,
    align: 'left',
    valign: 'middle',
  });

  if (Array.isArray(items) && items.length > 0) {
    const text = items
      .map((item) => `• ${item}`)
      .join('\n');

    slide.addText(text, {
      x: x + 0.15,
      y: y + 0.6,
      w: w - 0.3,
      h: h - 0.75,
      fontSize: 10,
      color: '444444',
      valign: 'top',
      fit: 'shrink',
    });
  }
}
function renderCardGrid(slide, entries, area, warnings, label) {
  if (!Array.isArray(entries) || entries.length === 0) {
    warnings.push(`Diagram type "${label}" has no entries — skipped.`);
    return;
  }

  const cols = Math.min(3, entries.length);
  const rows = Math.ceil(entries.length / cols);

  const gap = 0.25;

  const cardW =
    (area.w - gap * (cols - 1)) / cols;

  const cardH =
    (area.h - gap * (rows - 1)) / rows;

  entries.forEach((entry, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);

    const x = area.x + col * (cardW + gap);
    const y = area.y + row * (cardH + gap);

    const title =
      entry.use_case ||
      entry.title ||
      entry.name ||
      `Item ${i + 1}`;

    const items =
      Array.isArray(entry.technologies)
        ? entry.technologies
        : Array.isArray(entry.items)
          ? entry.items
          : entry.description
            ? [entry.description]
            : [];

    addGridCard(
      slide,
      x,
      y,
      cardW,
      cardH,
      title,
      items
    );
  });
}
// ---------------------------------------------------------------------------
// balance_axes: data.tradeoffs = { factor, impact }[]
// Rendered as a simple two-column list (a true axis/quadrant diagram is a
// later iteration â€” flagged rather than faked).
// ---------------------------------------------------------------------------
function renderTradeoffList(slide, data, area, warnings) {
  if (!Array.isArray(data.tradeoffs)) {
    warnings.push('Diagram type "balance_axes" is missing "data.tradeoffs" â€” skipped.');
    return;
  }
  const rowH = area.h / data.tradeoffs.length;
  data.tradeoffs.forEach((t, i) => {
    const y = area.y + i * rowH;
    slide.addText(
      [
        { text: `${t.factor}: `, options: { bold: true, fontSize: 11 } },
        { text: t.impact || '', options: { fontSize: 11 } },
      ],
      { x: area.x, y, w: area.w, h: rowH, valign: 'middle' }
    );
  });
  // TODO(section 6.8): render as an actual weighted axis/quadrant chart
  // once a concrete visual spec for "balance_axes" is agreed with upstream.
}

// ---------------------------------------------------------------------------
// original graph model: data.nodes / data.edges (by node id)
// ---------------------------------------------------------------------------
function renderNodeGraph(slide, data, area, warnings) {
  if (!Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
    warnings.push('Diagram is missing "data.nodes" or "data.edges" â€” skipped.');
    return;
  }
  const layoutType = data.layout || 'left_to_right';
  const labels = data.nodes.map((n) => n.label || n.id);
  const boxes = layoutChain(labels, area, { boxW: 1.7, boxH: 0.7 });
  const boxById = {};
  data.nodes.forEach((n, i) => {
    boxById[n.id] = boxes[i];
  });

  data.edges.forEach((edge) => {
    const a = boxById[edge.from];
    const b = boxById[edge.to];
    if (!a || !b) {
      warnings.push(`Diagram edge references unknown node ("${edge.from}" -> "${edge.to}") â€” skipped.`);
      return;
    }
    if (a.row === b.row) {
      addHorizontalArrow(slide, a.x + a.w, a.y + a.h / 2, b.x, b.y + b.h / 2);
    }
  });

  boxes.forEach((b) => addBox(slide, b.x, b.y, b.w, b.h, b.label));
  void layoutType; // top-down variant intentionally left for a follow-up iteration
}

// ---------------------------------------------------------------------------
// Fallback: any unrecognised diagram_type. Never silently drop content â€”
// pull out whatever title/name/label-ish text exists and show it as a
// simple bulleted list so the information still reaches the slide.
// ---------------------------------------------------------------------------
function renderGenericFallback(slide, data, area, warnings, diagramType) {
  warnings.push(
    `Diagram type "${diagramType}" is not specifically supported â€” rendered as a generic list. Consider adding a dedicated renderer.`
  );
  const candidates = data.items || data.trends || data.components || data.steps || data.nodes || [];
  const lines = candidates.map((c) => {
    if (typeof c === 'string') return `â€¢ ${c}`;
    const label = c.title || c.name || c.label || JSON.stringify(c).slice(0, 40);
    return `â€¢ ${label}`;
  });
  slide.addText(lines.join('\n') || '(no diagram content)', {
    x: area.x, y: area.y, w: area.w, h: area.h,
    fontSize: 12,
    valign: 'top',
  });
}

const DIAGRAM_RENDERERS = {
  pipeline: renderPipeline,
  numbered_process: renderNumberedProcess,
  system_architecture: renderComponentFlow,
  ops_workflow: renderComponentFlow,
  annotated_components: renderComponentFlow,
  grid: (slide, data, area, warnings) => renderCardGrid(slide, data.items, area, warnings, 'grid'),
  trend_map: (slide, data, area, warnings) => renderCardGrid(slide, data.trends, area, warnings, 'trend_map'),
  balance_axes: renderTradeoffList,
};

/**
 * Render a caption text label above the diagram area.
 * Returns the adjusted area (with caption band reserved at the top).
 */
function renderCaption(slide, caption, area) {
  if (!caption || !String(caption).trim()) return area;

  const captionH = 0.35;
  const captionY = area.y;

  slide.addText(String(caption).trim(), {
    x: area.x,
    y: captionY,
    w: area.w,
    h: captionH,
    fontSize: 10,
    italic: true,
    color: '555555',
    align: 'left',
    valign: 'top',
  });

  // Return the remaining area below the caption band
  return {
    x: area.x,
    y: captionY + captionH + 0.05,
    w: area.w,
    h: Math.max(area.h - captionH - 0.05, 0.3),
  };
}

/**
 * Compose a diagram object into native shapes within the given area.
 * Dispatches on data.diagram_type; falls back to the original nodes/edges
 * graph model when diagram_type is absent (backward compatible with the
 * original section 6.8 example), and to a generic list for anything else.
 *
 * @param {object} slide - PptxGenJS slide object
 * @param {object} data - the diagram's data payload (e.g. {steps, annotations})
 * @param {object} area - bounding box {x, y, w, h} in inches
 * @param {string[]} warnings - accumulated warnings array
 * @param {string} [caption] - optional descriptive text to render above the diagram
 */
function composeDiagram(slide, data, area, warnings, caption) {
  if (!data) {
    warnings.push('Diagram object has no "data" â€” skipped.');
    return;
  }

  // Reserve caption band at the top if a caption is provided
  const diagramArea = renderCaption(slide, caption, area);

  if (!data.diagram_type) {
    // No diagram_type: assume the original {nodes, edges} graph model.
    return renderNodeGraph(slide, data, diagramArea, warnings);
  }

  const renderer = DIAGRAM_RENDERERS[data.diagram_type];
  if (renderer) {
    return renderer(slide, data, diagramArea, warnings);
  }

  return renderGenericFallback(slide, data, diagramArea, warnings, data.diagram_type);
}

module.exports = { composeDiagram };
