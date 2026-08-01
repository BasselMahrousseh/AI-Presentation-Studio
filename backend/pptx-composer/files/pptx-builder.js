/**
 * pptx-builder.js
 *
 * Per 06_Template_and_PPTX_Engineering.md section 6.2:
 *   SlideSpec -> Layout Resolver -> PPTX Object Builder -> PPTX + Object Map + Warnings
 *
 * Per AGENTS.md section 11:
 * - Keep text, tables, charts, shapes and connectors native where possible.
 * - Do not position objects using model-generated pixel coordinates.
 * - Validate package integrity, relationships, content types and object IDs.
 *
 * Supported object types today (per section 6.5 Object mapping rules):
 *   - text     -> native text box
 *   - table    -> native PowerPoint table
 *   - diagram  -> native shapes + connectors (section 6.8 graph model)
 *   - citation -> text object (section 6.5: "Text object or speaker-note entry")
 * Not yet implemented (explicitly warned, never silently dropped):
 *   - chart, timeline, icon, image
 *
 * Object identity: upstream producers may send either "id" or "object_id"
 * on each object (both appear across the spec examples). We normalise to
 * a single accessor so the rest of this module doesn't care which one
 * arrived.
 */

const PptxGenJS = require('pptxgenjs');
const { resolvePosition, SLIDE_WIDTH_IN, SLIDE_HEIGHT_IN } = require('./layout-engine');

const TYPOGRAPHY = {
  title: { fontSize: 28, bold: true },
  subtitle: { fontSize: 18, bold: false, color: '555555' },
  body: { fontSize: 14, bold: false },
  architecture: { fontSize: 12, bold: false },
  reference: { fontSize: 9, bold: false, color: '888888', italic: true },
};

function objectId(obj) {
  return obj.object_id || obj.id || '(missing id)';
}

// ---------------------------------------------------------------------------
// text
// ---------------------------------------------------------------------------
function composeTextObject(slide, obj, warnings) {
  const pos = resolvePosition(obj.role, warnings);
  const typo = TYPOGRAPHY[obj.role] || TYPOGRAPHY.body;

  slide.addText(obj.text || '', {
    x: pos.x,
    y: pos.y,
    w: pos.w,
    h: pos.h,
    fontSize: typo.fontSize,
    bold: !!typo.bold,
    italic: !!typo.italic,
    color: typo.color,
    align: obj.direction === 'rtl' ? 'right' : 'left',
    // TODO(section 6.7): real text measurement/fitting instead of PptxGenJS autofit.
  });
}

// ---------------------------------------------------------------------------
// table
// ---------------------------------------------------------------------------
function composeTableObject(slide, obj, warnings) {
  const pos = resolvePosition(obj.role, warnings);

  if (!Array.isArray(obj.columns) || !Array.isArray(obj.rows)) {
    warnings.push(`Table object "${objectId(obj)}" is missing "columns" or "rows" — skipped.`);
    return;
  }

  const headerRow = obj.columns.map((c) => ({
    text: String(c),
    options: { bold: true, fill: { color: 'EEEEEE' } },
  }));
  const bodyRows = obj.rows.map((row) => row.map((cell) => ({ text: String(cell) })));

  slide.addTable([headerRow, ...bodyRows], {
    x: pos.x,
    y: pos.y,
    w: pos.w,
    h: pos.h,
    fontSize: 12,
    border: { type: 'solid', color: 'CCCCCC', pt: 0.5 },
    autoPage: false,
  });
}

// ---------------------------------------------------------------------------
// diagram — per section 6.8: graph model -> deterministic geometry ->
// grouped native shapes/connectors. This is a first, deliberately simple
// implementation: single-row (left_to_right) or single-column
// (layered_top_down) placement, straight connectors between adjacent
// nodes only. Arbitrary graph layouts (branching, cycles) are a later
// iteration — flagged as a TODO below rather than silently mishandled.
// ---------------------------------------------------------------------------
function layoutDiagramNodes(nodes, layoutType, area) {
  const count = nodes.length;
  const positions = {};

  const boxW = layoutType === 'layered_top_down' ? Math.min(2.4, area.w) : Math.min(1.9, (area.w - (count - 1) * 0.4) / count);
  const boxH = 0.7;

  if (layoutType === 'layered_top_down') {
    const gapY = (area.h - count * boxH) / Math.max(count - 1, 1);
    nodes.forEach((node, i) => {
      positions[node.id] = {
        x: area.x + (area.w - boxW) / 2,
        y: area.y + i * (boxH + gapY),
        w: boxW,
        h: boxH,
      };
    });
  } else {
    // default: left_to_right
    const gapX = (area.w - count * boxW) / Math.max(count - 1, 1);
    nodes.forEach((node, i) => {
      positions[node.id] = {
        x: area.x + i * (boxW + gapX),
        y: area.y + (area.h - boxH) / 2,
        w: boxW,
        h: boxH,
      };
    });
  }

  return positions;
}

function composeDiagramObject(slide, obj, warnings, pptx) {
  const pos = resolvePosition(obj.role, warnings);
  const data = obj.data;

  if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
    warnings.push(`Diagram object "${objectId(obj)}" is missing "data.nodes" or "data.edges" — skipped.`);
    return;
  }

  const layoutType = data.layout || 'left_to_right';
  const nodePositions = layoutDiagramNodes(data.nodes, layoutType, pos);

  // Draw connectors first so boxes render on top of the lines.
  for (const edge of data.edges) {
    const from = nodePositions[edge.from];
    const to = nodePositions[edge.to];
    if (!from || !to) {
      warnings.push(
        `Diagram object "${objectId(obj)}": edge references unknown node ("${edge.from}" -> "${edge.to}") — skipped.`
      );
      continue;
    }

    if (layoutType === 'layered_top_down') {
      const startX = from.x + from.w / 2;
      const startY = from.y + from.h;
      const endY = to.y;
      slide.addShape('line', {
        x: startX,
        y: startY,
        w: 0,
        h: endY - startY,
        line: { color: '999999', width: 1.5, endArrowType: 'triangle' },
      });
    } else {
      const startX = from.x + from.w;
      const startY = from.y + from.h / 2;
      const endX = to.x;
      slide.addShape('line', {
        x: startX,
        y: startY,
        w: endX - startX,
        h: 0,
        line: { color: '999999', width: 1.5, endArrowType: 'triangle' },
      });
    }
    // TODO(section 6.8): edge labels are not yet rendered. Add a small
    // addText call at the connector midpoint once label collision with
    // the line itself is handled.
  }

  // Draw node boxes + labels on top.
  for (const node of data.nodes) {
    const p = nodePositions[node.id];
    slide.addShape('roundRect', {
      x: p.x,
      y: p.y,
      w: p.w,
      h: p.h,
      fill: { color: 'F2F6FC' },
      line: { color: '4472C4', width: 1 },
      rectRadius: 0.06,
    });
    slide.addText(node.label || node.id, {
      x: p.x,
      y: p.y,
      w: p.w,
      h: p.h,
      align: 'center',
      valign: 'middle',
      fontSize: 11,
      color: '1F3864',
    });
  }
  // TODO(section 6.8): only chain-style / tree-style graphs are laid out
  // sensibly by this simple positional algorithm. Branching or cyclic
  // graphs need a real graph-layout algorithm before this is production-ready.
}

// ---------------------------------------------------------------------------
// citation — per section 6.5: "Text object or speaker-note entry".
// Rendered here as a small footer-style text object.
// ---------------------------------------------------------------------------
function composeCitationObject(slide, obj, warnings) {
  const typo = TYPOGRAPHY.reference;
  slide.addText(obj.text || '', {
    x: 0.5,
    y: SLIDE_HEIGHT_IN - 0.4,
    w: SLIDE_WIDTH_IN - 1.0,
    h: 0.3,
    fontSize: typo.fontSize,
    italic: typo.italic,
    color: typo.color,
    align: obj.direction === 'rtl' ? 'right' : 'left',
  });
}

const OBJECT_COMPOSERS = {
  text: composeTextObject,
  table: composeTableObject,
  diagram: composeDiagramObject,
  citation: composeCitationObject,
};

/**
 * Compose a validated DeckSpec into a PptxGenJS presentation.
 * Accepts either { slides: SlideSpec[] } or a single SlideSpec object
 * (auto-wrapped into a one-slide deck) — some upstream services may send
 * one slide at a time for slide-level regeneration (section 1.7 workflow C).
 */
function composeDeck(deckSpecOrSlideSpec) {
  const deckSpec = Array.isArray(deckSpecOrSlideSpec.slides)
    ? deckSpecOrSlideSpec
    : { slides: [deckSpecOrSlideSpec] };

  if (!Array.isArray(deckSpec.slides) || deckSpec.slides.length === 0) {
    throw new Error('deckSpec.slides must be a non-empty array of SlideSpec objects');
  }

  const pptx = new PptxGenJS();
  pptx.defineLayout({ name: 'AIPS_16x9', width: SLIDE_WIDTH_IN, height: SLIDE_HEIGHT_IN });
  pptx.layout = 'AIPS_16x9';

  const warnings = [];
  const objectMap = {};

  deckSpec.slides.forEach((slideSpec, slideIndex) => {
    if (!slideSpec.slide_id) {
      warnings.push(`Slide at index ${slideIndex} is missing "slide_id".`);
    }
    if (!Array.isArray(slideSpec.objects)) {
      warnings.push(`Slide "${slideSpec.slide_id || slideIndex}" has no "objects" array — empty slide created.`);
    }

    const slide = pptx.addSlide();

    for (const obj of slideSpec.objects || []) {
      const composer = OBJECT_COMPOSERS[obj.type];
      const id = objectId(obj);

      if (!composer) {
        warnings.push(
          `Slide "${slideSpec.slide_id}" object "${id}": type "${obj.type}" is not yet implemented in the composer. Object skipped.`
        );
        objectMap[id] = { slide_id: slideSpec.slide_id, type: obj.type, status: 'unsupported' };
        continue;
      }

      composer(slide, obj, warnings, pptx);
      objectMap[id] = { slide_id: slideSpec.slide_id, type: obj.type, status: 'composed' };
    }

    if (slideSpec.speaker_notes) {
      slide.addNotes(slideSpec.speaker_notes);
    }
  });

  return { pptx, warnings, objectMap };
}

module.exports = { composeDeck };
