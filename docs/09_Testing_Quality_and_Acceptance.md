# 9. Testing, Quality and Acceptance

## 9.1 Test pyramid

### Unit tests

- Schema validation and domain rules.
- Layout selection and constraint calculation.
- Provider adapters with recorded fixtures.
- Access-control policies.
- Lineage, versioning and idempotency.

### Contract tests

- Workspace/API OpenAPI contract.
- Model gateway structured output.
- Internal PPTX composer contract tests.
- Object storage and database repositories.
- Internal editor or PowerPoint add-in callbacks when introduced.

### Integration tests

- Upload through export with synthetic documents.
- Failure/retry at every job stage.
- Cancellation and resume.
- Template compilation and rendering.
- Arabic/RTL deck generation.

### End-to-end tests

- Real browser workflow in the GenAI Workspace.
- PPTX opened in Microsoft PowerPoint.
- Export/download authorisation.
- Version and audit verification.

## 9.2 Golden deck suite

Maintain a version-controlled set of approved test inputs and expected characteristics:

1. Architecture and engineering design deck.
2. Technical architecture deck.
3. KPI and financial-style chart deck using synthetic data.
4. Weekly project status deck.
5. English/Arabic bilingual deck.
6. Arabic RTL deck.
7. Existing poorly formatted PPTX requiring beautification.
8. Long source document converted to 10 slides.
9. Dense table deck.
10. Deck with generated hero imagery.

Golden tests assert structure and quality thresholds rather than pixel-perfect identity for every slide. Stable deterministic components may use visual-diff tolerances.

## 9.3 Quality scorecard

| Dimension | Weight | Examples |
|---|---:|---|
| Brand/template fidelity | 20 | colours, fonts, masters, spacing, locked objects |
| Visual quality | 20 | balance, hierarchy, whitespace, alignment |
| Native editability | 15 | text, tables, charts and shapes editable |
| Storyline/content | 15 | logical sequence, clear slide message, concision |
| PowerPoint round-trip | 10 | opens without repair, survives save/reopen |
| AI editing precision | 10 | selected-slide change without collateral changes |
| Arabic/RTL | 5 | shaping, direction, mixed-language alignment |
| Security/operability | 5 | lineage, classification, no external calls |

Pass threshold: 80/100 overall and no critical gate failure.

## 9.4 Automated PPTX tests

- ZIP and OOXML package integrity.
- Slide count and relationship consistency.
- Presence of slide masters and layouts.
- No object outside canvas.
- No text overflow where detectable.
- Minimum font size.
- Required branding objects.
- Editable object count by type.
- Notes and citations present where required.
- No macros, OLE or unexpected external relationships.

## 9.5 Visual regression

- Render every golden deck slide using the controlled renderer.
- Compare structural regions and perceptual image difference.
- Allow expected content variation but flag layout shifts, clipping and missing elements.
- Store before/after images for template, renderer and model releases.
- A human reviewer approves baseline changes.

## 9.6 AI evaluation

### Structured output

- JSON schema pass rate.
- Additional-property violations.
- Required-field completion.
- Object ID stability across repair.

### Grounding

- Citation precision and recall.
- Unsupported claim rate.
- Correct source-page mapping.

### Visual QA model

- Defect precision/recall against human-labelled slides.
- Severity calibration.
- False-positive repair rate.

### Arabic

- Human rating for grammar, terminology, RTL, punctuation and mixed-language layout.

## 9.7 Security tests

- Malicious PDF/PPTX corpus.
- Macro/OLE/ActiveX rejection.
- Zip bomb and oversized image.
- Prompt injection inside source documents.
- SSRF through image links.
- Cross-project IDOR.
- Token replay and expired JWT.
- Export of a restricted project by unauthorised user.
- Secret and PII leakage in logs.

## 9.8 Performance tests

Profiles:

- 10-slide prompt-only deck.
- 10-slide deck from a 30-page PDF.
- 20-slide deck with five generated images.
- 50 concurrent outline jobs.
- 20 concurrent complete-generation jobs.
- Burst of 100 slide-regeneration requests.

Measure queue delay, model latency, rendering time, database load, object-store throughput and failure recovery.

## 9.9 Definition of done for a feature

A feature is done only when:

- Requirement and acceptance criteria are linked.
- API/schema changes are documented.
- Unit and integration tests pass.
- Security and authorisation tests pass.
- Observability is included.
- Error and rollback behaviour is defined.
- User and AI-agent documentation is updated.
- No critical/high vulnerability is open.
- Human reviewer approves the resulting deck behaviour when visual output changes.
