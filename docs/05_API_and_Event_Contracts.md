# 5. API and Event Contracts

## 5.1 API conventions

- Base path: `/api/presentation-studio/v1`.
- JSON uses `snake_case` or the existing Workspace convention consistently; this pack uses `snake_case`.
- IDs are UUIDv7 where supported, otherwise UUIDv4.
- Dates use RFC 3339 UTC timestamps.
- Errors follow RFC 9457 problem details.
- All list endpoints support cursor pagination.
- Mutations support `Idempotency-Key`.
- Resource versions use ETag and `If-Match`.

## 5.2 Core endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/projects` | Create a presentation project |
| GET | `/projects/{project_id}` | Read project and permissions |
| POST | `/projects/{project_id}/sources` | Register/upload a source file |
| POST | `/projects/{project_id}/decks` | Create a logical deck |
| POST | `/decks/{deck_id}/generations` | Start outline or full deck generation |
| GET | `/jobs/{job_id}` | Read durable job status |
| GET | `/jobs/{job_id}/events` | SSE progress stream |
| POST | `/jobs/{job_id}:cancel` | Request job cancellation |
| GET | `/decks/{deck_id}/versions/{version_id}` | Read deck version manifest |
| POST | `/decks/{deck_id}/versions/{version_id}/slides/{slide_no}:regenerate` | Regenerate a selected slide |
| POST | `/decks/{deck_id}/versions/{version_id}/slides/{slide_no}:edit` | Apply natural-language or structured edit |
| POST | `/decks/{deck_id}/versions/{version_id}:export` | Create PPTX/PDF export |
| GET | `/templates` | List approved templates |
| POST | `/templates` | Create draft template package |
| POST | `/templates/{template_id}/versions/{version_id}:publish` | Publish approved template version |
| GET | `/assets` | Search approved/generated assets |
| GET | `/admin/usage` | Usage and quality metrics for authorised administrators |

## 5.3 Example generation request

```json
{
  "mode": "full_deck",
  "template_version_id": "018f...",
  "brief": {
    "title": "AI Coding Agent Weekly Update",
    "audience": "CTIO leadership",
    "objective": "Summarise adoption, productivity and next actions",
    "language": "en",
    "slide_count": 8,
    "tone": "technical",
    "classification": "INTERNAL"
  },
  "source_ids": ["018f-source-1"],
  "options": {
    "require_outline_approval": true,
    "generate_images": true,
    "include_speaker_notes": true,
    "citation_mode": "speaker_notes"
  }
}
```

## 5.4 Job response

```json
{
  "job_id": "018f-job-1",
  "status": "CREATED",
  "resource_type": "deck_generation",
  "resource_id": "018f-deck-1",
  "events_url": "/api/presentation-studio/v1/jobs/018f-job-1/events"
}
```

## 5.5 SSE event model

Event names:

- `job.started`
- `stage.started`
- `stage.progress`
- `outline.ready`
- `slide.generated`
- `slide.rendered`
- `slide.qa_completed`
- `job.awaiting_user`
- `job.completed`
- `job.failed`
- `job.cancelled`
- `heartbeat`

Example:

```text
event: stage.progress
id: 37
data: {"job_id":"018f-job-1","stage":"GENERATING","progress":62,"message":"Generated slide 5 of 8"}
```

Events are resumable through `Last-Event-ID`. The durable job record remains authoritative if events are missed.

## 5.6 Error model

```json
{
  "type": "https://errors.eand.local/presentation/unsupported-source",
  "title": "Unsupported source document",
  "status": 422,
  "code": "AIPS-SRC-004",
  "detail": "The uploaded PPTX contains macros and cannot be processed.",
  "instance": "/api/presentation-studio/v1/projects/.../sources/...",
  "correlation_id": "018f-corr-1",
  "retryable": false
}
```

Error code families:

- `AIPS-AUTH-*` identity and authorisation.
- `AIPS-SRC-*` upload, scanning and parsing.
- `AIPS-AI-*` model, schema and grounding.
- `AIPS-TPL-*` templates and layout.
- `AIPS-PPTX-*` composition, rendering and export.
- `AIPS-JOB-*` queue, timeout, cancellation and retry.
- `AIPS-DATA-*` database and storage.

## 5.7 Internal service interfaces

### ReasoningProvider

```python
class ReasoningProvider(Protocol):
    async def generate_structured(
        self,
        *,
        model_alias: str,
        messages: list[Message],
        response_schema: dict,
        request_context: ModelRequestContext,
    ) -> StructuredModelResponse: ...
```

### ImageProvider

```python
class ImageProvider(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> GeneratedAsset: ...
```

### PresentationEngine

```python
class PresentationEngine(Protocol):
    async def compile_template(self, package: TemplatePackage) -> CompiledTemplate: ...
    async def compose(self, deck_spec: DeckSpec, template: CompiledTemplate) -> BinaryArtifact: ...
    async def patch_slide(self, request: SlidePatchRequest) -> BinaryArtifact: ...
```

### Renderer

```python
class Renderer(Protocol):
    async def render(self, pptx: BinaryArtifact, options: RenderOptions) -> RenderSet: ...
```

Domain services depend on these interfaces, not external library types.

## 5.8 Webhook and callback security

When a future internal editor or PowerPoint add-in sends callbacks:

- Use short-lived signed editor tokens.
- Validate issuer, audience, expiry, document key and callback nonce.
- Restrict callback network source where possible.
- Reject callbacks for stale or unknown deck versions.
- Store edits as a new immutable version after antivirus and package validation.

## 5.9 MCP exposure

A future MCP server may expose approved tools:

- `create_presentation_project`
- `generate_deck_outline`
- `generate_deck`
- `get_generation_status`
- `regenerate_slide`
- `export_deck`

MCP tools must use the same API, RBAC and audit controls. They must not bypass user approval or gain direct database/object-storage access.
