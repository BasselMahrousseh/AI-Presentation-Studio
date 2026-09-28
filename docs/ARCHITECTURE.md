# AI Presentation Studio — Architecture Reference

The standalone architecture reference for this repo — read this first. `CLAUDE.md` is the short
working-notes file (business context, durable lessons, open items). Full history for anything removed or
resolved is in git (`git log -- docs/ARCHITECTURE.md CLAUDE.md`).

## 1. What this project is

The presentation-generation **backend behind the "Presentation Studio" feature of GenAI-Workspace**.
It started as an internal e& (Etisalat) fork of **Presenton**, an open-source AI presentation generator.
It replaces employees generating decks with whatever consumer AI tool they prefer, which leaked internal
content with no audit trail. Hard constraint: **all LLM inference stays inside an e&-contracted Azure
OpenAI tenant.** Success is measured on accuracy, security and cost (none instrumented in production yet).

End users never talk to this repo directly. Every Studio screen (new deck, outline review, editor, chat,
export, dashboard) lives in the Workspace UI (`GenAI-Workspace-UI`, `src/features/studio`, served at
`/app/studio/*`), which calls this FastAPI server. The Workspace backend (orchestrator) also calls it to
create a deck from a Workspace chat.

**September 2026 cleanup.** Everything outside that flow was deleted: the standalone Next.js UI
(`servers/nextjs`), the Docker/nginx/`start.js` single-container stack, the TemplateV2 "standard" deck
pipeline and bundled templates, Studio's local login/API tokens/user management, every LLM provider
except Azure OpenAI, runtime key switching (`userConfig.json`, provider settings), Presenton Cloud,
Codex OAuth, Ollama, themes, fonts, community decks, webhooks, the MCP server, stock image search, and
the dead database tables (Alembic `d5f7b9c1e3a4`). `tests/unit/test_route_contract.py` now pins the exact
route list below; the Workspace UI's matching TemplateV2 editor was removed in the same pass.

## 2. Layout

```
studio-dev/ (worktree of AI-Presentation-Studio, branch feature/workspace-identity -> Dev-Backend)
├── servers/fastapi/        FastAPI backend + SQLite/Postgres (the whole product)
│   └── .env                Committed backend config: Azure OpenAI, image settings, service key
├── presentation-export/    Gitignored prebuilt Node/Puppeteer bundle + PPTX converter (see §6)
├── resources/document-extraction/   LiteParse runner (Node) used to read uploaded documents
├── scripts/sync-presentation-export.cjs   Downloads/patches the export bundle
├── package.json            Node deps the backend shells out to (LiteParse, sharp)
└── Dockerfile              FastAPI-only image (Python + Node + Chromium)
```

Locally, `run_studio.sh` (GenAI-Workspace root) starts FastAPI on :8011; the Workspace runs on :3000 and
proxies browser calls to it (`GenAI-Workspace-UI/src/lib/studio-proxy.ts`). In the container the app
listens on :8000 (`CMD python server.py --host 0.0.0.0 --port 8000`).

## 3. Content model — Smart HTML

Every deck is a **Smart** deck: the LLM writes each slide as a Tailwind `<section>` HTML fragment
(`slides.html_content`). Generation is `_stream_smart_presentation` in `api/v1/ppt/endpoints/presentation.py`
calling `utils/llm_calls/generate_smart_presentation.py`: one streamed call for up to 20 slides,
parallel 10-slide chunks for longer outline-driven decks, per-slide repair for slides that fail the
render-based layout check (`utils/smart_slide_layout.py`, rendered in headless Chromium through
`presentation-export`). The e& brand template (`utils/smart_brand_templates.py`) splices a fixed cover and
thank-you slide around the generated content.

A `generation_mode="standard"` presentation row is the **outline draft**: `/generation` creates it, the
outline is generated and reviewed on it, then "Generate Standard" (Smart, no e& template) or "Generate
e& deck" creates a new Smart presentation from the approved outline (`source_presentation_id` links the
two for feedback). Legacy TemplateV2 decks still in a database are left untouched but are no longer
listed or opened.

## 4. Backend — FastAPI (`servers/fastapi`)

### 4.1 Startup

`api/main.py` loads `servers/fastapi/.env` (`override=False`: real env vars win), mounts the routers,
`/app_data` (user files) and `/static` (icons, vendor JS). `api/lifespan.py` runs Alembic when
`MIGRATE_DATABASE_ON_STARTUP=true`, creates missing tables, and fails fast if Azure OpenAI or (unless
`DISABLE_IMAGE_GENERATION`) the image provider is not configured. LLM calls go through `llmai` with an
`AzureOpenAIClientConfig` (Responses API) from `utils/llm_config.py`; any `LLM` value other than `azure`
is rejected.

### 4.2 Routes (the complete list — enforced by `test_route_contract.py`)

| Flow | Routes (`/api/v1/ppt` unless shown) |
|---|---|
| New deck | `POST /files/upload`, `POST /files/decompose`, `POST /template/extract-color-palette`, `POST /presentation/create` |
| Outline | `GET /outlines/stream/{id}` (SSE), `GET`/`PUT /outlines/{id}`, `POST /outlines/{id}/quality-flags/acknowledge` |
| Deck + editor | `GET /presentation/stream/{id}` (SSE, Smart only), `GET /presentation/{id}`, `PATCH /presentation/update`, `PATCH /presentation/slide_update`, `POST /slide/edit-html`, `GET /icons/search` |
| Dashboard | `GET /presentation/all` (Smart decks only), `DELETE /presentation/{id}`, `POST /presentation/{id}/duplicate`, `PATCH /presentation/{id}/favorite` |
| Images | `POST /images/upload`, `GET /images/uploaded`, `GET /images/generated`, `GET /images/generate`, `DELETE /images/{id}` |
| Chat | `GET /chat/conversations`, `GET /chat/history`, `DELETE /chat/conversation`, `POST /chat/message/stream` (SSE) |
| Feedback | `GET /feedback/{id}`, `PUT /feedback/{id}/{stage}`, `GET /api/v1/admin/feedback[?format=csv]` |
| Export | `POST /presentation/{id}/export`, `POST /presentation/export/chart-capture`, `POST /presentation/export/table-capture` |

Chat: a "standard" (outline-draft) presentation gets outline-only tools and prompt
(`services/chat/prompts.py`); a Smart deck gets the HTML-slide tools. The Workspace currently mounts the
chat only on the outline page (see `CLAUDE.md` open items).

### 4.3 Auth (`api/middlewares.py`, `api/v1/auth/principal.py`)

Studio has no accounts of its own. A request is authenticated by one of:

- **Workspace JWT** (HS256, `WORKSPACE_JWT_SECRET`), as `Authorization: Bearer` or the `studio_token`
  cookie the Workspace proxy mirrors for `<img>`/EventSource. Users map to `user.external_subject`
  (created on first use) and are never admins; every query is owner-scoped (`services/database.py`).
- **Service key** (`STUDIO_SERVICE_API_KEY`, constant-time compare) — the Workspace orchestrator's
  `PRESENTATION_STUDIO_API_KEY`. With `X-On-Behalf-Of: <subject>` it acts as that user (deck creation
  from chat). Without it, it may only call `/api/v1/admin/*` (the feedback export); anything else is 403.

`DISABLE_AUTH=true` (local dev only) skips auth; rows then have a null owner. The export renderer can
only send a cookie, so a bearer caller's Workspace JWT is handed to it as `studio_token=<jwt>`.
Chart/table capture sinks are unauthenticated by design (server-minted uuid4 tokens, `sendBeacon`).

## 5. Where the UI lives

`GenAI-Workspace-UI/src/features/studio`. Its Smart slide renderers (`SmartHtmlSlide`,
`SmartHtmlEditor`, the export page's `SmartHtmlPdfSlide`) inject sanitized HTML into the page and share
one Tailwind browser runtime; arbitrary-value utilities are written inline on injection
(`lib/smart-slide-arbitrary-styles.ts`). Previews used to be sandboxed iframes, which Chrome blocked from
loading the runtimes from a local-network origin (unstyled slides while streaming, blank thumbnails).
Those files used to be synced from this repo's Next.js app; that sync is retired and the Workspace copies
are the originals now.

## 6. Export pipeline — PPTX/PDF, native charts & tables

`POST /presentation/{id}/export` → `utils/export_utils.py::export_presentation()` →
`services/export_task_service.py` runs `node presentation-export/index.cjs <task.json>`. That bundle
(Puppeteer inside; gitignored, downloaded and patched by `scripts/sync-presentation-export.cjs`) opens the
**Workspace UI's** `/pdf-maker` page (`NEXT_PUBLIC_URL` must be the Workspace origin) in headless Chromium
and prints it (PDF) or hands it to the closed-source converter `presentation-export/py/convert-*`
(`BUILT_PYTHON_MODULE_PATH`) for PPTX. A semaphore caps Chromium spawns (`EXPORT_TASK_MAX_CONCURRENCY`,
default 3).

**Native charts and tables** (`services/pptx_native_chart_service.py`, `pptx_native_table_service.py`):
the export page captures live Chart.js and table data via `navigator.sendBeacon` to
`/export/chart-capture` and `/export/table-capture`; a post-pass swaps the flattened images for real,
editable PPTX objects. Scatter/polar-area/bubble charts stay images.

**Standing lesson**: python-pptx does no OOXML schema validation, and Microsoft's documentation has been
wrong for this format here before. Real "PowerPoint needs to repair this file" bugs were only ever
caught by opening the exported file in real PowerPoint — do that before shipping any OOXML change.

## 7. Generation entry points

`/generation` (Workspace) has two buttons, both Smart: **"Generate Standard"** (no `smart_template`,
optionally restyled with the palette of an attached reference `.pptx`) and **"Generate e& deck"**
(`smart_template: "eand"`). Both create the outline draft and open the outline page; the deck is created
from the approved outline. The e& template reserves a fixed cover + thank-you slide
(`EAND_FIXED_SLIDE_COUNT = 2`, on top of the content slides) and keeps content in a safe area above a
fixed footer; the fixed brand markup is never sent to the model. The Workspace chat hand-off
(orchestrator `presentation_studio.py`) creates the outline draft the same way.

## 8. Deployment

`Dockerfile` builds a FastAPI-only image: a uv-installed venv, the export bundle with sharp, LiteParse,
Chromium and Noto fonts, and warmed FastEmbed caches. Required env: Azure OpenAI (`AZURE_OPENAI_*`),
`WORKSPACE_JWT_SECRET`, `STUDIO_SERVICE_API_KEY`, `NEXT_PUBLIC_URL` (Workspace UI origin for
`/pdf-maker`), `APP_DATA_DIRECTORY`, and `DATABASE_URL` for Postgres/MySQL (SQLite otherwise; every
deployment so far has been SQLite). CI (`.github/workflows/test-all.yml`) runs the FastAPI test suite
and verifies the export runtime.

## 9. History worth knowing

- An outline-flag idempotency bug (`has_explicit_slide_structure` flipping to `false` on a repeat
  stream) was fixed by persisting the flag in its own column with a data-driven backfill —
  `BUG_REPORT_has_explicit_slide_structure_idempotency.md`.
- A DB session held open across a multi-minute Smart stream (pool exhaustion risk on Postgres) was fixed
  by opening short-lived sessions per unit of work in `stream_presentation`.
- Several Smart-mode overflow classes (canvas, table, Grid/Flexbox min-width squeeze) are guarded by
  real-render pixel checks plus deterministic inline-style guards, not heuristics alone.
- Multiple PPTX-corruption bugs in the native chart/table export were found only in real PowerPoint.

## 10. Where to go deeper

- `CLAUDE.md` — business context, durable lessons, open items.
- `STUDIO_IN_WORKSPACE_STATUS.md` (GenAI-Workspace folder root) — history of the migration into the
  Workspace, including the September 2026 cleanup.
- `BUG_REPORT_has_explicit_slide_structure_idempotency.md` — the bug summarized in §9.
