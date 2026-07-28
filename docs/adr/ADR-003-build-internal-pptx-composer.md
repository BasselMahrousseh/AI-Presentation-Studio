# ADR-003: Build an Internal PPTX Composer

**Status:** Accepted

## Decision
Develop a TypeScript/Node.js PPTX composer owned by the team. Use PptxGenJS behind internal abstractions and isolated OOXML patch modules for reviewed gaps.

## Consequences
The team owns composition quality and roadmap. External library types do not cross the composer contract. Golden PowerPoint and render tests are mandatory.
