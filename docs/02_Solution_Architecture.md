# 2. Solution Architecture

## 2.1 Architectural principles

1. **Extend the existing Workspace.** Reuse identity, navigation, quotas, audit, file-upload and UI standards.
2. **Separate orchestration from chat.** Presentation generation is a durable multi-stage workflow, not a single synchronous LLM request.
3. **Develop the core engine internally.** PPTX composition, template resolution, QA and repair are internal services owned by the engineering team.
4. **Use structured intermediate representations.** Models generate validated JSON; deterministic services create files.
5. **Preserve native editability.** Rasterisation is used for preview and decorative imagery, not as the source slide representation.
6. **Validate before rendering, inspect after rendering.** Structural checks precede visual QA.
7. **Immutable versioning.** Deck, slide, template, prompt and schema versions are never rewritten after publication.
8. **Least privilege and no public egress.** Every service has a narrow identity, network policy and storage scope.

## 2.2 System context

```text
Author / Reviewer
       |
       v
Existing e& GenAI Workspace
       |
       v
Presentation API and Orchestrator
       |-------------------------------|
       v               v               v
Enterprise Model   Internal PPTX    Retrieval / Template
Gateway             Composer         Services
       |               |               |
       +---------------+---------------+
                       |
             Oracle 23ai + Object Store
                       |
                PowerPoint-compatible
                   PPTX / PDF output
```

## 2.3 Runtime containers

```text
apps/
  workspace-ui
services/
  presentation-api
  presentation-orchestrator
  template-registry
  pptx-composer-api
workers/
  ingestion-worker
  planning-worker
  composition-worker
  asset-worker
  rendering-worker
  quality-worker
  export-worker
packages/
  domain
  contracts
  model-client
  pptx-ir
  security
  observability
```

### Workspace UI

- Project and deck management.
- Upload, outline review, previews, quality findings and exports.
- Uses existing OIDC and design system.
- Stores no authoritative project state only in browser storage.

### Presentation API

- Validates JWT, RBAC, input schemas and idempotency keys.
- Exposes project, source, generation, slide-edit, quality and export APIs.
- Returns durable job IDs and streams progress through SSE.
- Performs no CPU-heavy parsing or rendering.

### Presentation Orchestrator

- Implements the job state machine.
- Resolves prompt, model, schema and template versions.
- Dispatches stage work and records checkpoints.
- Enforces retry, timeout, cancellation and repair limits.
- Publishes progress and terminal events.

### Ingestion Worker

- Malware scans, validates MIME/type and rejects unsupported encrypted or active content.
- Uses Docling/native parsers in a sandbox.
- Extracts text, tables, images, slide/object inventory and source coordinates.
- Produces canonical chunks and provenance records.

### Planning Worker

- Generates `DeckBrief` and `DeckPlan` through the model gateway.
- Validates schema and grounding references.
- Supports explicit user outline approval.

### Composition Worker

- Generates or updates `SlideSpec` objects.
- Resolves template layout, design tokens and semantic placeholders.
- Calls the internal PPTX composer through a versioned contract.
- Never writes OOXML directly from model output.

### Internal PPTX Composer

The composer is a dedicated service developed by the team. Recommended implementation:

- TypeScript/Node.js runtime.
- PptxGenJS as the primary high-level construction library.
- Internal OOXML patch utilities for unsupported package-level features.
- Deterministic layout, chart, diagram and text-fitting modules.
- No model calls inside the composer.
- Contract input: validated `DeckSpec` / `SlideSpec` plus template package.
- Contract output: PPTX artefact, object map, warnings and integrity report.

### Rendering Worker

- Renders PPTX to PNG/PDF using a controlled LibreOffice build.
- Records renderer build, fonts and configuration.
- Generates thumbnails and full-resolution slide images.
- Runs in a hardened container without public egress.

### Quality Worker

- Runs schema, geometry, package, font, contrast and data checks.
- Calls a multimodal model only after deterministic checks pass.
- Produces structured `QAReport` findings.
- Creates minimal patches against stable object IDs.

### Template Registry

- Stores template manifests, design tokens, masters, layouts, sample renders and approval status.
- Publishes immutable template versions.
- Runs compatibility tests before publication.

### Export Worker

- Packages PPTX, PDF, PNG previews and lineage manifest.
- Runs final integrity and malware scan.
- Writes immutable artefacts and generates controlled download references.

## 2.4 Internal service contracts

| Caller | Callee | Protocol | Contract |
|---|---|---|---|
| Workspace | Presentation API | HTTPS REST + SSE | OpenAPI 3.1 |
| API | Orchestrator | Internal command API | Typed commands |
| Orchestrator | Workers | Queue message | Versioned event schema |
| Planning/QA | Model Gateway | OpenAI-compatible HTTPS | Model alias + JSON schema |
| Composition Worker | PPTX Composer | Internal REST/gRPC | `DeckSpec` and result contract |
| Workers | Oracle 23ai | DB driver | Repository interfaces |
| Workers | Object Store | S3-compatible HTTPS | Versioned object keys |
| Renderer | Object Store | S3-compatible HTTPS | Input/output artefacts |

## 2.5 Job state machine

```text
CREATED
  -> INGESTING
  -> PLANNING
  -> AWAITING_OUTLINE_APPROVAL (optional)
  -> GENERATING
  -> COMPOSING
  -> RENDERING
  -> INSPECTING
  -> REPAIRING -> COMPOSING (bounded loop)
  -> READY
  -> EXPORTING
  -> COMPLETED

Any active state may transition to FAILED or CANCELLED according to policy.
```

Each state transition is persisted with:

- job ID and attempt ID;
- stage name and version;
- input artefact references;
- output artefact references;
- correlation and trace IDs;
- start/end timestamps;
- retry count and error classification.

## 2.6 Deployment topology

- Kubernetes namespaces separated by environment.
- Stateless APIs deployed active-active.
- Worker pools separated by workload and scaling profile.
- CPU-heavy rendering and parsing isolated from API pods.
- GPU inference hosted by the enterprise AI platform and accessed only through the model gateway.
- Oracle 23ai and object storage use enterprise HA/DR patterns.
- Network policies allow only explicitly required service-to-service paths.
- Temporary filesystem mounts are encrypted, size-limited and cleared after use.

## 2.7 Technology baseline

| Layer | Baseline |
|---|---|
| Front end | Existing Next.js GenAI Workspace |
| API/orchestration | Python 3.12, FastAPI, Pydantic v2 |
| Async execution | Redis Streams or approved enterprise broker behind an abstraction |
| PPTX composition | TypeScript, Node.js, PptxGenJS, internal OOXML utilities |
| Parsing | Docling plus native OOXML parsers |
| Rendering | Hardened LibreOffice headless workers |
| Metadata | Oracle 23ai |
| Binary storage | Enterprise S3-compatible object storage |
| Observability | OpenTelemetry, enterprise logs, metrics and traces |
| Testing | Pytest, Vitest/Jest, Playwright, golden PPTX/render tests |

## 2.8 Quality attributes

### Modifiability

Model implementations, parser libraries and renderers are replaceable behind internal contracts. The PPTX composer remains internally controlled and its public contract is independent of PptxGenJS types.

### Reliability

Every stage is idempotent and resumable. A worker may be terminated without losing the durable job state.

### Security

Uploaded documents are untrusted. Model calls receive only sanitised, delimited content. No model receives shell, database or unrestricted file/network tools.

### Explainability

Each generated object can be traced to its source evidence, prompt version, model alias, template version and QA/repair history.
