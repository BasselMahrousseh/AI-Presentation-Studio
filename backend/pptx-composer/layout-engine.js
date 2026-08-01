/**
 * layout-engine.js
 *
 * Per 06_Template_and_PPTX_Engineering.md section 6.2 ("Layout Resolver")
 * and AGENTS.md section 11: "Do not position objects using model-generated
 * pixel coordinates. Use template-relative coordinates and deterministic
 * layout algorithms."
 *
 * This is a deliberately minimal starting point: one layout ("standard")
 * with slots for title/body/table/comparison roles. Real templates (see
 * section 6.3 "Template package") would define many archetypes with their
 * own layouts.json files — this hard-coded version is a placeholder until
 * the Template Registry (section 2.3) exists.
 *
 * All units are inches, matching PptxGenJS defaults and the 16:9 slide
 * size assumed below (13.33in x 7.5in).
 */

const SLIDE_WIDTH_IN = 13.33;
const SLIDE_HEIGHT_IN = 7.5;
const MARGIN_IN = 0.5;

// role -> { x, y, w, h } in inches. Extremely simple single-layout baseline.
const ROLE_POSITIONS = {
  title: { x: MARGIN_IN, y: 0.4, w: SLIDE_WIDTH_IN - MARGIN_IN * 2, h: 1.0 },
  subtitle: { x: MARGIN_IN, y: 1.4, w: SLIDE_WIDTH_IN - MARGIN_IN * 2, h: 0.6 },
  body: { x: MARGIN_IN, y: 1.6, w: SLIDE_WIDTH_IN - MARGIN_IN * 2, h: SLIDE_HEIGHT_IN - 2.2 },
  comparison: { x: MARGIN_IN, y: 1.6, w: SLIDE_WIDTH_IN - MARGIN_IN * 2, h: SLIDE_HEIGHT_IN - 2.2 },
  kpi: { x: MARGIN_IN, y: 1.6, w: SLIDE_WIDTH_IN - MARGIN_IN * 2, h: SLIDE_HEIGHT_IN - 2.2 },
};

/**
 * Resolve the bounding box for a given object role.
 * Falls back to the "body" slot with a warning if the role is unknown,
 * rather than throwing — composition should degrade gracefully and
 * report the issue in the composition report (section 6.2 output: "warnings").
 */
function resolvePosition(role, warnings) {
  const pos = ROLE_POSITIONS[role];
  if (pos) return pos;

  warnings.push(`Unknown object role "${role}" — falling back to body layout slot.`);
  return ROLE_POSITIONS.body;
}

module.exports = {
  SLIDE_WIDTH_IN,
  SLIDE_HEIGHT_IN,
  resolvePosition,
};
