# 10. Implementation Plan and Backlog

## 10.1 Delivery strategy

Deliver vertical engineering slices that produce a valid editable PPTX early. Build the internal composer and contracts first; avoid starting with a large browser editor or a complex autonomous multi-agent implementation.

## 10.2 Phase 0 - Technical discovery

**Indicative duration:** 2-3 weeks

Outputs:

- Approved source-file and golden-deck corpus.
- Confirmed classification and security controls.
- Benchmark of available enterprise model endpoints.
- PptxGenJS and OOXML capability spike.
- Controlled LibreOffice render pipeline.
- Initial template package and font inventory.
- Finalised `DeckBrief`, `DeckPlan`, `SlideSpec` and `QAReport` schemas.

Exit criteria:

- Internal dependencies and container images approved.
- Model gateway accessible from the development namespace.
- A hand-authored `SlideSpec` can be composed, rendered and opened in PowerPoint.

## 10.3 Phase 1 - End-to-end technical baseline

**Indicative duration:** 8-10 weeks

### EPIC-1 Workspace integration

- Presentation Studio route and project dashboard.
- Create-deck workflow.
- Upload, outline review, progress streaming and download.

### EPIC-2 API and orchestration

- Project/deck/version/job APIs.
- Durable state machine.
- Queue workers, retries, cancellation and SSE events.

### EPIC-3 Ingestion and planning

- PDF, DOCX, XLSX, PPTX and Markdown parsing.
- Source chunking and provenance.
- Deck brief and outline generation.
- User outline approval.

### EPIC-4 Internal PPTX composer

- Composer API and contracts.
- Template package loader.
- Text, image, table and shape objects.
- Native charts.
- Diagram engine baseline.
- OOXML integrity validation.

### EPIC-5 Rendering and quality

- PNG/PDF rendering.
- Deterministic geometry and package validation.
- Initial multimodal QA report.

### EPIC-6 Governance

- OIDC/RBAC.
- Model-gateway integration.
- Classification, audit and usage metrics.
- Network egress restrictions.

Exit criteria:

- Prompt/document to editable PPTX works end to end.
- Required acceptance gates in Section 1 pass.

## 10.4 Phase 2 - Quality and controlled pilot

**Indicative duration:** 8-12 weeks

- Slide-level natural-language editing.
- Minimal object-level repair.
- Advanced diagrams, charts and table layouts.
- Approved template/asset retrieval.
- Arabic and mixed-direction production templates.
- Template registry UI and approval workflow.
- Quality dashboards and user feedback capture.
- Load, resilience, security and penetration testing.
- PowerPoint add-in API design if required.

## 10.5 Phase 3 - Production hardening

**Indicative duration:** 10-14 weeks

- High availability and production SLOs.
- Capacity and queue prioritisation.
- Full retention, DLP and publication workflow.
- Disaster recovery and restore testing.
- Operational runbooks and support ownership.
- Internal structured editing expansion.
- Optional PowerPoint add-in developed by the team.

## 10.6 Prioritised backlog

| Priority | Item |
|---|---|
| P0 | Internal PPTX composer service and contract |
| P0 | End-to-end prompt/document to editable PPTX |
| P0 | OIDC, project access, idempotency and audit |
| P0 | Template package and immutable versioning |
| P0 | Render/preview and PowerPoint integrity tests |
| P0 | No-external-egress controls |
| P1 | Outline approval and single-slide regeneration |
| P1 | Deterministic plus multimodal QA |
| P1 | Source lineage and citations |
| P1 | Arabic/RTL template and QA |
| P1 | Usage and quality dashboards |
| P2 | Approved slide/asset retrieval |
| P2 | Advanced diagram and chart engines |
| P2 | Internal structured Workspace editor |
| P2 | PowerPoint add-in |
| P3 | Real-time collaboration |

## 10.7 Minimum team

- Technical product owner.
- Solution architect / technical lead.
- Two Python back-end engineers.
- One TypeScript PPTX/composition engineer.
- One front-end engineer.
- One AI/ML engineer.
- One QA automation engineer.
- Shared platform, security, database and template-design support.

## 10.8 Engineering responsibility matrix

| Area | Product | Architecture | Backend | PPTX/TS | AI/ML | Frontend | QA | Platform/Security |
|---|---|---|---|---|---|---|---|---|
| Scope and priority | A/R | C | C | C | C | C | C | C |
| Architecture and ADRs | C | A/R | C | C | C | C | C | C |
| API and domain model | C | A | R | C | C | C | C | C |
| PPTX composer | I | A | C | R | C | I | C | C |
| Model prompts/evaluation | C | C | C | C | A/R | I | C | C |
| Workspace UI | C | C | C | I | C | A/R | C | C |
| Security release gate | I | C | C | C | C | C | C | A/R |
| Quality acceptance | A | C | C | C | C | C | R | C |

## 10.9 Major risks

| Risk | Impact | Mitigation |
|---|---|---|
| High-level PPTX library lacks a required feature | High | Keep internal abstraction; add reviewed OOXML patch modules and golden fixtures |
| LibreOffice render differs from PowerPoint | High | Golden round-trip tests and periodic PowerPoint reference renders |
| Text measurement differs across environments | High | Pin fonts and measurement library; compare composer and renderer metrics |
| Multimodal QA causes repeated changes | Medium | Deterministic checks first, confidence thresholds and bounded repair |
| Arabic shaping or mixed direction is inconsistent | High | Dedicated fonts, templates, object-level direction and test corpus |
| Source contains malware or prompt injection | High | Sandbox, sanitisation, no model tools and strict network controls |
| GPU capacity is constrained | High | Queue priorities, concurrency limits, caching and capacity benchmark |
| Scope expands into full design suite | High | Maintain non-goals, phase gates and architecture review |

## 10.10 Engineering checkpoints

- **Checkpoint A:** after composer spike - confirm PptxGenJS baseline and OOXML gap list.
- **Checkpoint B:** after first end-to-end golden deck - confirm contracts and template approach.
- **Checkpoint C:** after 20-deck quality run - approve controlled pilot only when quality/security gates pass.
- **Checkpoint D:** before production - approve SLOs, capacity, DR, support and retention.
