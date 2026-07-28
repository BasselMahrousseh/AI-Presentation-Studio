# 6. Template and PPTX Engineering

## 6.1 Objective

Build an internal, deterministic composition capability that converts validated semantic slide specifications into standards-compliant, editable PPTX packages. The model proposes content and semantic structure; the composer owns geometry, layout, OOXML and file validity.

## 6.2 Internal composition architecture

```text
SlideSpec
   |
   v
Layout Resolver -> Text Measurement -> Diagram/Chart Engines
   |                         |
   +-------------------------+
               |
               v
        PPTX Object Builder
               |
               v
      OOXML Package Validator
               |
               v
       PPTX + Object Map + Warnings
```

### Recommended implementation split

- `pptx-composer-api`: validates requests and manages composition jobs.
- `layout-engine`: chooses layouts and computes object bounds.
- `text-engine`: measures text, applies typography and performs bounded fitting.
- `chart-engine`: creates native charts and embeds structured data.
- `diagram-engine`: generates native shapes and connectors from graph models.
- `asset-engine`: normalises SVG/PNG/JPEG and records lineage.
- `pptx-builder`: wraps PptxGenJS behind internal abstractions.
- `ooxml-patcher`: performs reviewed package-level patches where the high-level library is insufficient.
- `pptx-validator`: validates ZIP package, relationships, content types and required parts.

## 6.3 Template package

```text
template-package/
  manifest.yaml
  source/
    template.pptx
  tokens/
    colours.json
    typography.json
    spacing.json
  layouts/
    title.json
    section.json
    comparison.json
    architecture.json
    table.json
    chart.json
  assets/
    logos/
    icons/
    backgrounds/
  previews/
  tests/
  CHANGELOG.md
```

A template package contains:

- Template ID, semantic version, owner and status.
- Supported languages, directions, aspect ratios and slide sizes.
- Theme colours, fonts, safe margins and spacing scale.
- Semantic layout definitions and placeholder constraints.
- Locked and protected brand elements.
- Approved icons, logos and decorative assets.
- Golden inputs and expected render snapshots.

## 6.4 Slide intermediate representation

The `SlideSpec` is independent of PptxGenJS and OOXML. It contains:

- Stable slide ID and object IDs.
- Semantic archetype and selected layout ID.
- Language and direction.
- Objects with role, content, hierarchy and constraints.
- Data bindings for charts and tables.
- Source references and review flags.
- Speaker notes.
- Locked/protected flags.
- Repair history.

Example:

```json
{
  "slide_id": "s-04",
  "archetype": "technical_comparison",
  "language": "en",
  "direction": "ltr",
  "objects": [
    {
      "id": "title-1",
      "type": "text",
      "role": "title",
      "text": "Architecture Options",
      "locked": false
    },
    {
      "id": "table-1",
      "type": "table",
      "role": "comparison",
      "columns": ["Option", "Benefits", "Constraints"],
      "rows": [["A", "...", "..."]]
    }
  ]
}
```

## 6.5 Object mapping rules

| Semantic object | PPTX representation |
|---|---|
| Title/body text | Native text box or placeholder |
| Table | Native PowerPoint table |
| KPI | Native text and shapes |
| Bar/line/pie chart | Native chart with embedded data where supported |
| Architecture diagram | Native shapes and connectors |
| Timeline | Grouped shapes and connectors |
| Icon | Approved SVG/EMF/PNG asset |
| Generated illustration | Raster image with alt text and lineage |
| Citation | Text object or speaker-note entry |

Complete slides must not be generated as raster images. A raster-only slide is allowed only when the user explicitly requests an image-only visual and the output is marked non-editable.

## 6.6 Layout resolution

1. Planner selects a semantic archetype.
2. Resolver filters layouts by language, direction, required object types and template compatibility.
3. Resolver scores candidate layouts using content size, hierarchy, visual density and constraints.
4. Text engine estimates line count and required bounds before composition.
5. Composer places objects using template-relative coordinates.
6. Overflow actions execute in order:
   - choose alternate layout;
   - reduce optional detail;
   - request a concise rewrite;
   - split content into another slide when allowed;
   - reduce font within approved minimums.
7. Renderer and QA validate the result.

## 6.7 Text measurement and fitting

- Use the actual approved font files installed in both composer and renderer images.
- Measure text using a deterministic library compatible with Node.js.
- Store measured font, size, line count and bounds in the composition report.
- Never reduce title/body text below template minimums.
- Preserve manual line breaks only when explicitly requested or required by the template.
- For Arabic, shape and measure RTL text using the same font environment as rendering.

## 6.8 Editable diagrams

The diagram engine accepts a graph model:

```json
{
  "layout": "layered_top_down",
  "nodes": [
    {"id": "workspace", "label": "GenAI Workspace", "kind": "application"},
    {"id": "orchestrator", "label": "Presentation Orchestrator", "kind": "service"}
  ],
  "edges": [
    {"from": "workspace", "to": "orchestrator", "label": "REST + SSE"}
  ]
}
```

The engine calculates geometry deterministically and creates grouped native shapes/connectors. The model chooses semantic nodes and relationships, not raw pixel coordinates.

## 6.9 Charts and tables

- Chart data must originate from structured input or verified extracted tables.
- Units, time periods and transformations are mandatory metadata.
- Chart type selection uses a controlled catalogue.
- Data and style remain editable in PowerPoint where supported.
- QA validates labels, legends, axes, formatting and data-to-visual consistency.
- Narrative text must not be converted into fabricated numeric charts.

## 6.10 PPTX package engineering

The composer must validate:

- ZIP package integrity.
- `[Content_Types].xml` entries.
- Relationships and target parts.
- Presentation, slide master, layout and theme references.
- Unique shape IDs and relationship IDs.
- Media references and MIME types.
- Notes and comments parts when enabled.
- Correct slide dimensions.
- No orphaned parts after patching.

Low-level OOXML patches require:

- A dedicated implementation module.
- Unit fixtures for before/after packages.
- Relationship/content-type validation.
- Golden PowerPoint-open tests.
- An ADR for any new patch category.

## 6.11 Existing PPTX import

- Preserve the source file unchanged.
- Extract masters, layouts, theme, fonts, colours and object inventory.
- Record unsupported features such as macros, OLE, ActiveX or third-party add-ins.
- Convert supported layouts into a draft internal template package.
- Preserve unsupported objects as opaque objects when possible.
- Create a new version for every modification.
- Report any object that cannot be round-tripped safely.

## 6.12 Internal structured editing

The first release does not implement a full browser PowerPoint editor. The Workspace may expose structured operations against semantic objects:

- Edit title/body text.
- Replace image.
- Update chart data.
- Change layout.
- Lock/unlock supported objects according to permission.
- Regenerate selected object or slide.
- Restore a prior deck version.

All edits update the `SlideSpec`, create a new immutable deck version, recompose affected slides and rerun QA.

## 6.13 Template definition of done

A template version is publishable only when:

- Owner and approver are recorded.
- Required archetypes have sample inputs and renders.
- English and declared Arabic/RTL variants pass tests.
- Fonts and assets are approved and installed.
- Safe margins, content limits and locked objects are defined.
- Golden deck generation has no critical defects.
- PPTX opens and round-trips in Microsoft PowerPoint.
