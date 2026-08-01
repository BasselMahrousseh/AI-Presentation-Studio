/**
 * pptx-builder.js
 *
 * Per 06_Template_and_PPTX_Engineering.md section 6.2:
 *   SlideSpec -> Layout Resolver -> PPTX Object Builder -> PPTX + Object Map + Warnings
 *
 * Per AGENTS.md section 11:
 * - Keep text, tables, charts, shapes and connectors native where possible.
 * - Do not position objects using model-generated pixel coordinates.
 *
 * Supported object types (per section 6.5's mapping table, extended for
 * the object types real upstream producers actually send):
 *   - text     -> native text box (role determines typography weight)
 *   - table    -> native PowerPoint table (columns/rows may be top-level
 *                 or nested under "data", both accepted)
 *   - diagram  -> dispatched to diagram-engine.js (multiple diagram_type shapes)
 *   - citation -> footer text object
 *   - callout  -> highlighted/accented text box (key takeaways, insights)
 *   - icon     -> placeholder labelled shapes (TODO: real icon asset library,
 *                 per section 6.5: "Icon -> Approved SVG/EMF/PNG asset")
 * Not yet implemented (explicitly warned, never silently dropped):
 *   - chart, timeline, image
 */

const PptxGenJS = require('pptxgenjs');
const { computeSlideLayout, SLIDE_WIDTH_IN, SLIDE_HEIGHT_IN } = require('./layout-engine');
const { composeDiagram } = require('./diagram-engine');

function objectId(obj) {
  return obj.object_id || obj.id || '(missing id)';
}

// Typography keyed by rough category, not exact role string, so unfamiliar
// role names (e.g. "headline" vs "title") still get sensible defaults.
function typographyFor(role) {
  const r = (role || '').toLowerCase();
  if (r === 'title' || r === 'headline') return { fontSize: 28, bold: true };
  if (r === 'subtitle' || r === 'subheadline') return { fontSize: 16, bold: false, color: '555555' };
  if (r === 'reference' || r === 'citation') return { fontSize: 9, italic: true, color: '888888' };
  return { fontSize: 13, bold: false };
}

// ---------------------------------------------------------------------------
// text
// ---------------------------------------------------------------------------
function composeText(slide, obj, area) {
  const typo = typographyFor(obj.role);
  const text = obj.text || '';
  // Preserve explicit newlines (checklists etc. arrive as "\n"-joined text).
  const lines = text.split('\n').map((line, i) => ({
    text: line,
    options: i === 0 ? {} : { breakLine: true },
  }));

  slide.addText(lines, {
    x: area.x, y: area.y, w: area.w, h: area.h,
    fontSize: typo.fontSize,
    bold: !!typo.bold,
    italic: !!typo.italic,
    color: typo.color,
    align: obj.direction === 'rtl' ? 'right' : 'left',
    valign: 'top',
  });
}

// ---------------------------------------------------------------------------
// table — accepts columns/rows either top-level or nested under "data"
// ---------------------------------------------------------------------------
function composeTable(slide, obj, area, warnings) {
  const columns = obj.columns || (obj.data && obj.data.columns);
  const rows = obj.rows || (obj.data && obj.data.rows);

  if (!Array.isArray(columns) || !Array.isArray(rows)) {
    warnings.push(`Table object "${objectId(obj)}" is missing columns/rows — skipped.`);
    return;
  }

  const headerRow = columns.map((c) => ({
    text: String(c),
    options: { bold: true, fill: { color: 'EEEEEE' }, fontSize: 11 },
  }));
  const bodyRows = rows.map((row) => row.map((cell) => ({ text: String(cell), options: { fontSize: 10 } })));

  slide.addTable([headerRow, ...bodyRows], {
    x: area.x, y: area.y, w: area.w, h: area.h,
    fontSize: 10,
    border: { type: 'solid', color: 'CCCCCC', pt: 0.5 },
    autoPage: false,
  });
}

// ---------------------------------------------------------------------------
// callout — visually distinct highlight box for key takeaways/insights
// ---------------------------------------------------------------------------
function composeCallout(slide, obj, area) {
  slide.addShape('roundRect', {
    x: area.x, y: area.y, w: area.w, h: area.h,
    fill: { color: 'FFF4E5' },
    line: { color: 'ED7D31', width: 1 },
    rectRadius: 0.08,
  });
  slide.addText(obj.text || '', {
    x: area.x + 0.15, y: area.y, w: area.w - 0.3, h: area.h,
    fontSize: 12,
    italic: true,
    color: '7A4A14',
    valign: 'middle',
    align: obj.direction === 'rtl' ? 'right' : 'left',
  });
}

// ---------------------------------------------------------------------------
// icon — TODO(section 6.5): replace with an approved SVG/EMF/PNG icon
// library lookup by name. Placeholder renders labelled circles so the
// information (which icons were requested) isn't silently lost.
// ---------------------------------------------------------------------------
function composeIcon(slide, obj, area, warnings) {
  const icons = (obj.data && obj.data.icons) || [];
  if (icons.length === 0) {
    warnings.push(`Icon object "${objectId(obj)}" has no "data.icons" — skipped.`);
    return;
  }
  warnings.push(
    `Icon object "${objectId(obj)}" rendered as placeholder labels — real icon assets not yet wired in (section 6.5).`
  );

  const gap = 0.2;
  const diameter = Math.min(0.7, (area.w - gap * (icons.length - 1)) / icons.length);
  const startX = area.x + (area.w - (icons.length * diameter + (icons.length - 1) * gap)) / 2;
  const y = area.y + (area.h - diameter) / 2;

  icons.forEach((iconName, i) => {
    const x = startX + i * (diameter + gap);
    slide.addShape('ellipse', {
      x, y, w: diameter, h: diameter,
      fill: { color: 'E7EEFB' },
      line: { color: '4472C4', width: 1 },
    });
    slide.addText(String(iconName), {
      x: x - 0.3, y: y + diameter + 0.05, w: diameter + 0.6, h: 0.3,
      fontSize: 8,
      align: 'center',
    });
  });
}

// ---------------------------------------------------------------------------
// citation — footer text
// ---------------------------------------------------------------------------
function composeCitation(slide, obj, area) {
  slide.addText(obj.text || '', {
    x: area.x, y: area.y, w: area.w, h: area.h,
    fontSize: 9,
    italic: true,
    color: '888888',
    align: obj.direction === 'rtl' ? 'right' : 'left',
    valign: 'middle',
  });
}

// ---------------------------------------------------------------------------
// diagram — delegates to diagram-engine.js
// ---------------------------------------------------------------------------
function composeDiagramObject(slide, obj, area, warnings) {
  // Pass obj.text as a descriptive caption rendered above the diagram shapes
  composeDiagram(slide, obj.data, area, warnings, obj.text);
}

const OBJECT_COMPOSERS = {
  text: (slide, obj, area, warnings) => composeText(slide, obj, area, warnings),
  table: composeTable,
  diagram: composeDiagramObject,
  citation: composeCitation,
  callout: composeCallout,
  icon: composeIcon,
};

/**
 * Compose a validated DeckSpec into a PptxGenJS presentation.
 * Accepts either { slides: SlideSpec[] } or a single SlideSpec object
 * (auto-wrapped into a one-slide deck).
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
    const objects = slideSpec.objects || [];
    if (objects.length === 0) {
      warnings.push(`Slide "${slideSpec.slide_id || slideIndex}" has no "objects" array — empty slide created.`);
    }

    const slide = pptx.addSlide();
    const positions = computeSlideLayout(objects);

    for (const obj of objects) {
      const composer = OBJECT_COMPOSERS[obj.type];
      const id = objectId(obj);
      const area = positions.get(obj);

      if (!composer) {
        warnings.push(
          `Slide "${slideSpec.slide_id}" object "${id}": type "${obj.type}" is not yet implemented in the composer. Object skipped.`
        );
        objectMap[id] = { slide_id: slideSpec.slide_id, type: obj.type, status: 'unsupported' };
        continue;
      }

      composer(slide, obj, area, warnings);
      objectMap[id] = { slide_id: slideSpec.slide_id, type: obj.type, status: 'composed' };
    }

    if (slideSpec.speaker_notes) {
      slide.addNotes(slideSpec.speaker_notes);
    }
  });

  return { pptx, warnings, objectMap };
}

module.exports = { composeDeck };
