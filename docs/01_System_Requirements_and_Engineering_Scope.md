# 1. System Requirements and Engineering Scope

**Project:** e& AI Presentation Studio  
**Version:** 1.0 - Internal Engineering Baseline  
**Owner:** AI Engineering & Factory  
**Target platform:** Existing e& GenAI Workspace  
**Deployment:** e& controlled on-premises or private enterprise environment  
**Delivery model:** Fully developed and operated by the e& engineering team

## 1.1 System overview

The project adds a governed presentation-generation and editing capability to the existing GenAI Workspace. The system converts prompts and enterprise documents into native editable PowerPoint files, applies approved design templates, renders previews, performs deterministic and multimodal quality inspection, supports controlled slide-level revisions and records complete provenance.

All application services, orchestration logic, template tooling, PPTX composition, quality-control logic, interfaces and operational controls are developed and maintained internally. Open-source libraries may be used as implementation dependencies after security and licence approval, but no external presentation platform is part of the target runtime architecture.

## 1.2 Engineering problem statement

A general-purpose LLM can generate narrative text, but it cannot reliably create a correct PowerPoint package by itself. The platform must coordinate multiple deterministic and AI stages to solve the following engineering problems:

1. Parse heterogeneous enterprise source files securely.
2. Convert user intent and evidence into a structured presentation plan.
3. Generate schema-valid semantic slide specifications.
4. Map semantic content to approved templates and layout constraints.
5. Compose valid OOXML/PPTX packages containing editable objects.
6. Render and inspect the generated output consistently.
7. Repair defects without destroying user edits or factual meaning.
8. Version every artefact and retain end-to-end lineage.
9. Enforce identity, authorisation, classification, retention, quotas and audit.
10. Support English, Arabic and mixed RTL/LTR layouts.

## 1.3 Engineering objectives

- Produce a usable first draft as a native editable PPTX.
- Keep text, tables, charts, shapes, connectors and notes editable wherever technically possible.
- Reuse Workspace authentication, RBAC, quotas, audit, UI components and model routing.
- Store durable metadata in Oracle 23ai and binary artefacts in enterprise object storage.
- Build the PPTX engine as an internal service with stable contracts and deterministic tests.
- Use capability-based model aliases instead of hard-coded model names.
- Achieve repeatable output through template constraints, deterministic validation, render inspection and bounded repair.
- Make the system safe for confidential internal documents with no unapproved external egress.

## 1.4 In scope

- Prompt-to-presentation generation.
- PDF, DOCX, XLSX, Markdown and PPTX ingestion.
- Existing-deck analysis and controlled improvement.
- Outline review and approval before full generation.
- Template registry and versioned design tokens.
- Native PPTX composition and PDF/PNG preview generation.
- Slide-level regenerate, rewrite, redesign and replace-asset operations.
- Editable charts, tables, timelines and architecture diagrams.
- Source lineage and citations in metadata or speaker notes.
- English, Arabic and bilingual presentation support.
- Deterministic QA, multimodal QA and bounded auto-repair.
- Project/deck/version management, audit and observability.
- Internal APIs for future PowerPoint add-in or Workspace editor integration.

## 1.5 Out of scope for the first release

- Replacing Microsoft PowerPoint as a complete professional authoring suite.
- Real-time collaborative editing.
- VBA, macros, OLE, ActiveX or embedded executable support.
- Arbitrary animation and transition generation.
- Autonomous publication or external distribution.
- Fine-tuning a foundation model specifically for presentation creation.
- Public internet stock-media search in the runtime environment.
- Automatic use of unsupported fonts or unapproved brand assets.

## 1.6 Engineering actors

### Presentation author
Creates or revises a presentation using prompts, documents, approved templates and generated previews.

### Reviewer
Reviews outline, source grounding, visual quality and final output; may request targeted changes.

### Template engineer
Builds, tests, versions and publishes template packages and layout constraints.

### Platform administrator
Operates services, models, quotas, storage, retention, monitoring and incident response.

### Security auditor
Reviews access, classification, data flow, model use, audit events and system configuration.

### Service account
Represents internal workers, renderers and model-gateway clients. Every service account has least-privilege permissions.

## 1.7 Main workflows

### A. Prompt or document to presentation

1. User creates a project and deck.
2. User selects language, template, audience profile, output length and classification.
3. User uploads source files or provides a prompt.
4. Ingestion scans, extracts, chunks and records provenance.
5. Planning produces a validated `DeckBrief` and `DeckPlan`.
6. User approves or edits the outline.
7. Composition generates a `SlideSpec` for each slide.
8. The internal PPTX composer maps specifications to native objects.
9. Rendering creates previews.
10. QA validates geometry, fidelity, grounding and visual quality.
11. Repair applies minimal patches when permitted.
12. A new immutable deck version is published for review and download.

### B. Improve an existing PPTX

1. Preserve the uploaded file as an immutable source artefact.
2. Extract masters, layouts, theme, fonts, object inventory and unsupported features.
3. Build a semantic representation of supported objects.
4. Apply user-requested operations to a new version.
5. Compose, render and compare the new version against the source.
6. Preserve unsupported objects where possible; otherwise report them explicitly.

### C. Edit one slide

1. User selects a slide and provides an instruction.
2. The API creates an edit command against a specific immutable source version.
3. The planning/repair service identifies affected object IDs.
4. A patch updates the `SlideSpec` without changing unrelated objects.
5. The composer creates a new deck version.
6. Rendering and QA run only for the changed slide and any dependent slides.

## 1.8 Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | Create projects, decks and immutable deck versions | Must |
| FR-002 | Upload and scan supported source files | Must |
| FR-003 | Extract text, tables, images, headings and provenance | Must |
| FR-004 | Generate and validate `DeckBrief` and `DeckPlan` | Must |
| FR-005 | Allow outline review and approval | Must |
| FR-006 | Generate schema-valid `SlideSpec` objects | Must |
| FR-007 | Resolve approved template layouts and design tokens | Must |
| FR-008 | Compose native editable PPTX objects | Must |
| FR-009 | Render slide previews and PDF | Must |
| FR-010 | Run deterministic and multimodal QA | Must |
| FR-011 | Apply bounded object-level repair | Must |
| FR-012 | Export PPTX, PDF, rendered slides and lineage manifest | Must |
| FR-013 | Regenerate or edit a single slide | Should |
| FR-014 | Import and analyse an existing PPTX | Should |
| FR-015 | Support Arabic, RTL and bilingual objects | Should |
| FR-016 | Retrieve approved templates, assets and prior patterns | Should |
| FR-017 | Provide template authoring and publication workflow | Should |
| FR-018 | Expose APIs for a future PowerPoint add-in | Could |
| FR-019 | Provide internal structured editing in Workspace | Could |

## 1.9 Non-functional requirements

### Security

- OIDC/JWT authentication and server-side RBAC on every operation.
- No public AI or image endpoint calls.
- No unapproved internet egress from workers.
- Malware scanning and content-type validation before parsing.
- Sandboxed extraction and rendering.
- Encryption in transit and at rest.
- No confidential source content in standard logs.
- Immutable audit for sensitive and mutating actions.

### Reliability

- Durable job state and stage checkpoints.
- Idempotency for every mutation.
- Safe retries with bounded attempts.
- Immutable version creation rather than in-place mutation.
- Recovery from worker termination at the last completed checkpoint.

### Performance

- API acknowledgement p95 under 2 seconds for accepted jobs.
- Preview generation streamed incrementally as slides complete.
- Text-focused ten-slide generation target p95 under 5 minutes in the PoC environment.
- Workload-specific queues and concurrency controls.

### Maintainability

- Strict internal contracts between orchestration, AI and composition layers.
- Model aliases, prompt IDs, schema versions and template versions recorded for every result.
- No external library type exposed in domain APIs.
- ADR required for architectural or dependency changes.

### Accessibility and localisation

- Keyboard-accessible Workspace interfaces.
- Alt text metadata for generated images.
- Explicit text direction and language on slide objects.
- Approved Arabic fonts installed in composition and rendering environments.

## 1.10 Acceptance gates

The technical baseline is accepted only when:

- Generated PPTX opens without a repair warning in Microsoft PowerPoint.
- At least 90% of core objects remain editable across the approved golden suite.
- No critical or high security findings remain open.
- No source artefact leaves approved storage or network boundaries.
- Deterministic QA reports no critical overflow, clipping or package-integrity defects.
- Arabic and English test decks pass manual and automated review.
- Every published deck version records model, prompt, template, source and QA lineage.
- The same input, configuration and seed produce reproducible structural output within defined tolerances.
