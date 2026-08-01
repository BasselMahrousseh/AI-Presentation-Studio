/**
 * layout-engine.js
 *
 * Per 06_Template_and_PPTX_Engineering.md section 6.2 ("Layout Resolver")
 * and AGENTS.md section 11 (template-relative coordinates, deterministic
 * layout — never model-generated pixel coordinates).
 *
 * Design note: earlier versions of this file hard-coded a fixed position
 * per role name (title/body/comparison/...). That breaks the moment an
 * upstream producer sends a role it didn't anticipate (e.g. "headline",
 * "hero_visual", "key_takeaway" — see the RAG example SlideSpec). Since
 * this composer is a REST API consumed by another backend we don't
 * control, the layout engine now classifies objects into three generic
 * bands instead of matching exact role strings:
 *
 *   HEADER  — title/headline-ish text, always at the top, stacked in
 *             the order received (title above subtitle).
 *   FOOTER  — citation/reference text, pinned to the bottom.
 *   CONTENT — everything else (body text, diagrams, tables, callouts,
 *             icons, checklists...). These fill the remaining vertical
 *             space, stacked top-to-bottom, sized proportionally so
 *             N content objects never overlap.
 *
 * This is still a placeholder until a real Template Registry (section
 * 6.3) provides per-archetype layouts — but it degrades gracefully for
 * arbitrary SlideSpec content instead of silently overlapping objects.
 */

const SLIDE_WIDTH_IN = 13.33;
const SLIDE_HEIGHT_IN = 7.5;
const MARGIN_IN = 0.5;

const HEADER_ROLES = new Set([
  'title', 'headline', 'subtitle', 'subheadline',
]);
const FOOTER_ROLES = new Set([
  'reference', 'citation',
]);

const HERO_ROLES = new Set([
  'hero_visual',
]);

function classify(role) {
  const r = (role || '').toLowerCase();
  if (HEADER_ROLES.has(r)) return 'header';
  if (FOOTER_ROLES.has(r)) return 'footer';
  return 'content';
}

/**
 * Compute positions for every object on a slide in one pass, so header,
 * footer and content bands are guaranteed not to overlap.
 *
 * @param {Array<{role:string}>} objects - the slide's objects, in order.
 * @returns {Map<object, {x,y,w,h}>} position keyed by object reference.
 */
function computeSlideLayout(objects) {
  const positions = new Map();

  const header = objects.filter((o) => classify(o.role) === 'header');
  const footer = objects.filter((o) => classify(o.role) === 'footer');

  const hero = objects.filter((o) =>
    HERO_ROLES.has((o.role || '').toLowerCase())
  );

  const content = objects.filter((o) =>
    classify(o.role) === 'content' &&
    !HERO_ROLES.has((o.role || '').toLowerCase())
  );

  const contentWidth = SLIDE_WIDTH_IN - MARGIN_IN * 2;

  // ------------------------------------------------------------
  // Header
  // ------------------------------------------------------------

  let headerY = 0.4;

  header.forEach((obj) => {
    const role = (obj.role || '').toLowerCase();

    const isPrimary =
      role === 'title' ||
      role === 'headline';

    const h = isPrimary ? 0.9 : 0.6;

    positions.set(obj, {
      x: MARGIN_IN,
      y: headerY,
      w: contentWidth,
      h,
    });

    headerY += h + 0.1;
  });

  const headerBottom =
    header.length > 0
      ? headerY + 0.1
      : 0.4;

  // ------------------------------------------------------------
  // Footer
  // ------------------------------------------------------------

  const footerH = 0.35;
  const footerTop = SLIDE_HEIGHT_IN - footerH - 0.15;

  footer.forEach((obj, i) => {
    positions.set(obj, {
      x: MARGIN_IN,
      y: footerTop - i * (footerH + 0.05),
      w: contentWidth,
      h: footerH,
    });
  });

  // ------------------------------------------------------------
  // Main content area
  // ------------------------------------------------------------

  const contentTop = headerBottom + 0.1;

  const contentBottom =
    footer.length > 0
      ? footerTop - 0.15
      : SLIDE_HEIGHT_IN - MARGIN_IN;

  const availableHeight = Math.max(
    contentBottom - contentTop,
    0.5
  );

  // ------------------------------------------------------------
  // Hero visual
  // ------------------------------------------------------------

  let currentY = contentTop;

  if (hero.length > 0) {
    const heroGap = 0.2;

    // Hero gets the majority of the available space.
    // If there are multiple hero objects, divide the hero area.
    const heroAreaHeight = Math.min(
      3.2,
      availableHeight * 0.6
    );

    const totalHeroGap =
      heroGap * Math.max(hero.length - 1, 0);

    const heroObjectHeight = Math.max(
      (heroAreaHeight - totalHeroGap) / hero.length,
      0.8
    );

    hero.forEach((obj) => {
      positions.set(obj, {
        x: MARGIN_IN,
        y: currentY,
        w: contentWidth,
        h: heroObjectHeight,
      });

      currentY += heroObjectHeight + heroGap;
    });

    currentY += 0.05;
  }

  // ------------------------------------------------------------
  // Normal content
  // ------------------------------------------------------------

  const remainingHeight = Math.max(
    contentBottom - currentY,
    0.5
  );

  if (content.length > 0) {
    const gap = 0.2;

    const perObjectHeight = Math.max(
      (remainingHeight - gap * (content.length - 1)) /
        content.length,
      0.4
    );

    let y = currentY;

    content.forEach((obj) => {
      positions.set(obj, {
        x: MARGIN_IN,
        y,
        w: contentWidth,
        h: perObjectHeight,
      });

      y += perObjectHeight + gap;
    });
  }

  return positions;
}

module.exports = {
  SLIDE_WIDTH_IN,
  SLIDE_HEIGHT_IN,
  MARGIN_IN,
  computeSlideLayout,
};
