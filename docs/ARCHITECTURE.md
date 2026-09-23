# AI Presentation Studio — Architecture Reference

Distilled from the live codebase (`studio-dev`, worktree of `AI-Presentation-Studio`, branch
`feature/workspace-identity`), `CLAUDE.md`'s session history, `SDD-AI-Presentation-Studio_v1.0.md`,
and `STUDIO_IN_WORKSPACE_STATUS.md`. Written as a standalone reference — read this before diving into
`CLAUDE.md`'s raw, chronological session notes.

## 1. What this project is

An internal e& (Etisalat) fork of **Presenton**, an open-source AI presentation generator
(`package.json` name is still `presenton`). It replaces employees generating decks with
whatever external consumer AI tool they personally prefer, which leaked internal content (strategy
docs, financials, customer data) to third parties with no audit trail. Hard constraint: **all LLM
inference stays inside an e&-contracted Azure OpenAI tenant** — no consumer/hosted API may see user
content. Success is measured on accuracy (faithful to source material), security (content stays
in-tenant, access is attributable), and cost — none of which is currently instrumented in production
(no eval harness, no audit log, no token/cost accounting).

On top of the inherited Presenton base, the team layers e&-specific work: a branded **"e& Smart
Mode"** generation template, UI reskin, and (in progress) porting the user-facing screens into a
separate **GenAI-Workspace** shell application (see §8).

## 2. Tech stack & repo layout

```
AI-Presentation-Studio/
├── servers/
│   ├── nextjs/        Next.js 16 + React 19 frontend        (port 3000)
│   └── fastapi/        FastAPI backend + SQLite/Postgres DB   (port 8000)
├── presentation-export/  Gitignored, downloaded prebuilt Node/Puppeteer bundle — PPTX/PDF renderer
├── templates/            Bundled legacy TemplateV2 layout JSON (seeded into DB on startup, see §3)
├── resources/             LiteParse document-extraction runner
├── layouts.json           Legacy layout registry
├── docker-compose.yml     production / production-gpu / development / development-gpu services
├── nginx.conf             Reverse proxy config used inside the Docker image
├── SDD-AI-Presentation-Studio_v1.0.md   Full solution design audit (architecture, data model, risk register)
└── CLAUDE.md               Raw chronological session log — root-cause diagnoses, fixed/open bugs
```

Two servers only; the browser talks to both through one Next.js "Proxy" (`servers/nextjs/proxy.ts`,
Next 16's rename of middleware):

```
Browser
  │
  ▼
Next.js (servers/nextjs, :3000)
  │  proxy.ts rewrites /api/v1/* and /api/v2/* → FastAPI (NextResponse.rewrite)
  │  SSE stream paths instead hit dedicated Route Handlers that pipe the FastAPI
  │  response through untouched (rewrite() buffers streams, breaking real-time SSE)
  ▼
FastAPI (servers/fastapi, :8000)
  │  SQLite (dev) / Postgres or MySQL (via DATABASE_URL, prod-capable, untested in this fork's own deployments)
  ▼
presentation-export/ (Puppeteer bundle, spawned as a subprocess, renders /pdf-maker headlessly)
```

In Docker, **nginx runs inside the container** (`start.js` + `nginx.conf`) and reverse-proxies the
host-facing port to Next.js (:3000) and FastAPI (:8000); it also handles `/api/v1/auth/verify`-based
image auth (`auth_request`) for `/app_data/images|uploads/...`.

## 3. Content model — Smart HTML

The real, live content path is **Smart HTML**: the LLM outputs a raw Tailwind `<section>` fragment
per slide directly, rendered via `SmartHtmlSlide.tsx` — an iframe + browser-side Tailwind JIT runtime
(`lib/tailwind-browser.ts`). For reasoning models, generation is typically one LLM call that "thinks"
silently, then emits all slides in a fast burst (`_stream_smart_presentation`, `?type=smart`). The e&
brand template (`smart_brand_templates.py`) is hardcoded literal HTML spliced around LLM-generated
content. Editing happens via the in-editor AI chat rewriting raw HTML (the feature exists but its
toggle button is commented out in `PresentationHeader.tsx`, so it's currently undiscoverable) or via
`POST /api/v1/ppt/slide/edit-html`, a prompt-driven single-slide regeneration used by the slide action
bar's "Regenerate Slide" button and the AI chat's tool-calling edits.

The codebase also carries a second, older structured slide model ("TemplateV2" — JSON content + a
schema-constrained UI element tree, a Konva canvas editor) inherited from upstream Presenton. It's
real, working code, but essentially unused in the live e&-configured app: the dashboard's main
generation entry (`/generation`) never invokes it, and it's reachable only through the secondary
`/upload` page's mode toggle. Not covered further here — treat it as legacy surface area, not part of
the product's real generation path.

## 4. Backend — FastAPI (`servers/fastapi`)

### 4.1 Bootstrap

`api/main.py`: loads `.env` (`load_dotenv(..., override=False)` — an already-set OS/Docker env var
always wins over the file), initializes Sentry if configured, mounts all routers, then mounts
`/app_data` (user files) and `/static` (fonts/vendor JS/CSS) as `StaticFiles`. `api/lifespan.py` runs
Alembic-adjacent startup checks (LLM provider configured, image provider configured unless disabled,
bootstrap-admin check).

### 4.2 Router map

All PPT-domain routers are mounted under `/api/v1/ppt` via `api/v1/ppt/router.py`; auth, admin,
webhook, mock, and async-task routers are top-level.

| Prefix | Router file | Purpose |
|---|---|---|
| `/api/v1/auth` | `api/v1/auth/router.py` | Session status, login/logout/setup, LDAP-adjacent identity, nginx `auth_request` target |
| `/api/v1/admin` | `api/v1/admin/router.py` | Provider settings, user management, feedback export |
| `/api/v1/webhook` | `api/v1/webhook/router.py` | Webhook subscribe/unsubscribe |
| `/api/v1/mock` | `api/v1/mock/router.py` | Test/mock endpoints |
| `/api/v1/async-tasks` (approx.) | `api/v1/async_tasks/router.py` | Generic async task polling (genuinely used by template creation) |
| `/api/v1/ppt/files` | `files.py` | Upload/decompose/update source documents |
| `/api/v1/ppt/fonts` | `fonts.py` | Custom font upload/list/delete |
| `/api/v1/ppt/outlines` | `outlines.py` | Outline CRUD + SSE outline generation |
| `/api/v1/ppt/slide` | `slide.py` | Single-slide edit (`/edit-html` for Smart HTML; `/edit` for the legacy TemplateV2 path) |
| `/api/v1/ppt/images` | `images.py` | Search/generate/upload/list/delete images |
| `/api/v1/ppt/icons` | `icons.py` | Icon search |
| `/api/v1/ppt/ollama`, `/openai`, `/anthropic`, `/google` | provider-availability probes for local/cloud LLM providers |
| `/api/v1/ppt/codex/auth` | `codex_auth.py` | OAuth device-code flow for a Codex-branded provider |
| `/api/v1/ppt/presentation` | `presentation.py` | **Core**: create/prepare/stream/edit/derive/export/list/delete presentations |
| `/api/v1/ppt/presentation/export` | `chart_capture.py`, `table_capture.py` | Native-chart/table capture + PPTX upgrade endpoints |
| `/api/v1/ppt/themes`, `/theme` | `theme.py`, `theme_generate.py` | Saved themes CRUD, AI theme generation |
| `/api/v1/ppt/chat` | `chat.py` | AI chat sidebar — history, message, SSE message stream |
| `/api/v1/ppt/template` | `template.py` | Custom Template Studio (create/edit/list/delete templates from an uploaded PPTX) |
| `/api/v1/ppt/community/presentations` | `community.py` | Community/shared deck browsing |
| `/api/v1/ppt/feedback` | `feedback.py` | Thumbs up/down generation feedback (outline + deck stage) |
| `/api/v1/ppt/layouts` | `layouts.py` | Layout registry |

### 4.3 Key endpoints (not exhaustive — see routers above for the full surface)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/ppt/presentation/create` | Creates a presentation row; entry point for both generation modes |
| `POST` | `/api/v1/ppt/presentation/prepare` | Prepares generation (template selection, slide count resolution) |
| `GET` | `/api/v1/ppt/presentation/stream/{id}` | **SSE.** Streams slide-burst (Smart, the live path) or slide-by-slide (legacy TemplateV2) generation. `?type=standard|smart` |
| `GET` | `/api/v1/ppt/outlines/stream/{id}` | **SSE.** Streams outline generation; also runs `detect_explicit_slide_count()` (see §9.1 for a fixed idempotency bug here) |
| `PUT` | `/api/v1/ppt/outlines/{id}` | Update outline |
| `POST` | `/api/v1/ppt/outlines/{id}/quality-flags/acknowledge` | Acknowledge a document-extraction quality flag before generating |
| `PATCH` | `/api/v1/ppt/presentation/update` | Update presentation metadata |
| `PATCH` | `/api/v1/ppt/presentation/slide_update` | Update a single slide record |
| `PATCH` | `/api/v1/ppt/presentation/{id}/favorite` | Star/unstar (Workspace dashboard feature) |
| `POST` | `/api/v1/ppt/presentation/edit` | Generate-and-export in one request (also used for re-export after edits) |
| `POST` | `/api/v1/ppt/presentation/derive` | Derive a new deck from an existing one |
| `POST` | `/api/v1/ppt/presentation/{id}/export` | Export by id |
| `POST` | `/api/v1/ppt/slide/edit-html` | Single-slide prompt-driven regeneration (Smart HTML) |
| `POST` | `/api/v1/ppt/presentation/export/chart-capture`, `/upgrade-charts` | Native PPTX chart pipeline (see §6) |
| `POST` | `/api/v1/ppt/presentation/export/table-capture`, `/upgrade-tables` | Native PPTX table pipeline (see §6) |
| `POST` | `/api/v1/ppt/chat/message`, `/message/stream` | AI chat — single response / SSE |
| `GET`/`PUT` | `/api/v1/ppt/feedback/{id}[/{stage}]` | Thumbs up/down; 409 on a stale generation id |
| `GET` | `/api/v1/admin/feedback[?format=csv]` | Admin feedback export |
| `GET` | `/api/v1/auth/status`, `/llm-status`, `/verify` | Session/LLM-config status; `/verify` is nginx's `auth_request` target |
| `POST` | `/api/v1/auth/setup`, `/login`, `/logout` | Local auth flows |

**Confirmed dead**, not wired to any frontend caller: `POST /presentation/generate`,
`/generate/async`, `GET /status/{id}` — the live generation path is `prepare` + `stream/{id}`.

**`/api/v2/ppt/presentation/*`** is not a second FastAPI router — it's proxied straight through to an
external **Presenton Cloud** service by `services/presenton_cloud_proxy.py` (`generate-html/init`,
`update`, `stream/`), reached only when the `presenton` OAuth/cloud LLM provider is selected.

### 4.4 Auth model

Session cookie (`presenton_session`) + `sk-presenton-*` API-key bearer tokens, one role bit
(`is_superuser`). `DISABLE_AUTH=true` bypasses auth entirely and `/auth/status` hardcodes
`username: "electron", role: "admin"` (a generic single-user bypass, not tied to the now-removed
Electron app). A parallel **Workspace JWT** bridge (`api/v1/auth/workspace_jwt.py`, HS256, claims
`sub`/`name`/`email`/`iat`/`exp`, no `iss`/`aud`) lets the GenAI-Workspace shell's own login token
authenticate directly against Studio — users are matched on a new `user.external_subject`, never
username, and Workspace users are never admins (see §8).

### 4.5 Async jobs

`AsyncTaskModel` is genuinely used for template creation (polled by the frontend). The equivalent
wrapper for presentation generation is the confirmed-dead `/generate/async` family above.

## 5. Frontend — Next.js (`servers/nextjs`)

Next.js 16.3.2 / React 19, App Router. `app/DashboardShell.tsx` wraps the authenticated app.

### 5.1 Live, reachable routes

| Route | Purpose |
|---|---|
| `/` | Dashboard (`DashboardPage`) — real app home |
| `/generation` | **Primary** generation entry (linked from dashboard's "Create with AI"). Two buttons, both Smart mode under the hood — see §7 for the label mismatch |
| `/upload` | **Secondary**, independent generation entry with a mode toggle that also exposes the legacy TemplateV2 path (see §3). Reachable from onboarding, the outline page's empty state, the community page, and the editor's error-recovery fallback — not dead despite not being on the main dashboard CTA |
| `/outline` | Outline review/edit, mandatory step before slide generation from `/generation` |
| `/presentation?id=` | Slide editor (Smart HTML iframe editor) |
| `/custom-template`, `/template-preview` | Template Studio |
| `/community`, `/theme`, `/settings` | Community browsing, theming, settings (incl. embedded `AdminPanel` tab) |
| `/templates` | Reachable only programmatically after custom-template creation; its sidebar nav links are disabled no-ops |
| `/admin` | No in-app links; reachable only by typing the URL (same `AdminPanel` also embeds in `/settings`) |
| `(export)/pdf-maker` | Headless render target only — never linked, used exclusively by the export pipeline (Puppeteer navigates here) |
| `/generate`, `/dashboard` | Legacy-URL redirect shims to `/generation` and `/` respectively |

### 5.2 Confirmed dead / orphaned (inherited from upstream Presenton)

`app/frontend/` (a whole alternate prototype dashboard, hardcodes `127.0.0.1:8000`, zero inbound
links), `/documents-preview`, `components/DashboardNav.tsx`, and the Next.js API routes
`api/github-stars`, `api/has-required-key`, `api/templates` (non-`v1`), `api/upload-image`.

### 5.3 SSE handling

`proxy.ts`'s `NextResponse.rewrite()` silently buffers SSE responses. The three real stream paths
(`/api/v1/ppt/presentation/stream/`, `/api/v2/ppt/presentation/stream/`,
`/api/v1/ppt/outlines/stream/`) are excluded and instead hit dedicated Route Handlers
(`app/api/v1/.../stream/[id]/route.ts`, via `lib/sse-proxy.ts`) that pipe the FastAPI response
through untouched. Any new SSE endpoint needs the same treatment.

### 5.4 Export — two independent implementations, know which one ran

- **FastAPI-driven**: `services/export_task_service.py`, used by `/edit`, `/derive`, and the main
  generate flow (`utils/export_utils.py::export_presentation()`).
- **Editor-button-driven**: the interactive "Export PPTX"/"Export PDF" buttons
  (`PresentationHeader.tsx`) go through a **completely separate** Next.js route
  (`app/api/export-presentation/route.ts` → `lib/run-bundled-presentation-export.ts`), which spawns
  the Puppeteer bundle directly from the Next.js process and never touches FastAPI.

Both point at the same headless `/pdf-maker` page and the same `presentation-export/` bundle, but a
fix to one does nothing for the other unless applied to both.

## 6. Export pipeline — PPTX/PDF, native charts & tables

Neither server renders PPTX/PDF itself. Both shell out to `presentation-export/` — a gitignored,
downloaded, **patched** (via `scripts/sync-presentation-export.cjs`'s `KNOWN_BUNDLE_PATCHES`) Node
bundle built on Puppeteer, which navigates headlessly to `/pdf-maker` and converts the rendered page.
A `threading.BoundedSemaphore` caps concurrent Chromium spawns per process
(`EXPORT_TASK_MAX_CONCURRENCY`, default 3, FastAPI side; `EXPORT_BUNDLE_MAX_CONCURRENCY`, default 2,
Next.js side — independent budgets, combined ceiling is their sum).

**Native chart export** (`services/pptx_native_chart_service.py`): a post-export pass swaps flattened
chart images for real, editable PPTX chart objects, driven by chart data captured live from the
resolved Chart.js instance on the export page (`lib/chart-export-capture.ts`, via
`navigator.sendBeacon` — a plain `fetch()` from inside `/pdf-maker` hangs Puppeteer's
`networkidle0` wait). Covers bar/horizontal-bar/stacked-bar/horizontal-stacked-bar/line/area/pie/
donut/radar; scatter/polar-area/bubble intentionally stay flattened images (no faithful PPTX
equivalent). Per-series colors, data labels, font, and axis order all carry through.

**Native table export** (`services/pptx_native_table_service.py`): the same capture/match/swap
pattern, independent token/store/endpoint pipeline from the chart one
(`table_capture_store.py`, `/export/table-capture` + `/export/upgrade-tables`). No custom per-cell
border color in v1 initially (python-pptx has no API for it) — since extended to bottom-border-only
via hand-authored OOXML, after explicit user sign-off given the corruption risk (see below).

**Standing lesson baked into this codebase, worth repeating**: python-pptx performs essentially zero
schema validation on OOXML it's asked to emit — several real "file needs repair, PowerPoint deletes
the whole slide" corruption bugs were found only by a human opening the real exported file in real
PowerPoint (e.g. `<c:dLblPos val="outEnd">` being legal on a pie chart but not a doughnut). Neither
python-pptx accepting a value nor Microsoft's own documentation has proven reliable for this file
format in this codebase's own history — real-PowerPoint verification is the only check that has ever
caught it.

## 7. Generation entry points — the label mismatch to know about

The live `/generation` page's two buttons are **both Smart mode** under the hood, despite their
labels: **"Generate Standard"** sends no `smart_template` (plain Smart HTML, no e& branding);
**"Generate e& deck"** sends `smart_template: "eand"`. "Standard" here does not mean the legacy
TemplateV2 path (see §3) — it's still Smart HTML, just without e& branding. Clicking either button
routes to `/outline?id=...&autostart=true` for mandatory outline review before slide generation —
there is no more direct-stream shortcut from this page.

The e& template reserves a fixed cover + thank-you slide (`EAND_FIXED_SLIDE_COUNT = 2`, *added on top*
of the requested content-slide count) and constrains the model to a content safe-area above a fixed
footer; the fixed brand markup is never sent to the model. If a `.pptx` is attached among source
files for an e& generation, its real shape-fill colors are extracted and used instead of the default
red/dark-blue/white/black palette.

## 8. Studio ⇄ GenAI-Workspace migration (in progress)

A separate, larger effort is porting Studio's user-facing screens (dashboard trimmed, `/generation`,
`/outline`, the presentation editor incl. chat + export) to run **inside** the GenAI-Workspace shell
UI, using Workspace's own shell/theme/login — Studio's FastAPI (+ a small headless renderer) stays a
separate deployment behind a same-origin proxy. `/theme`, `/community`, `/settings`, `/admin`,
templates, and `/upload` are explicitly **not** ported (all dead-code/out-of-scope for the migration,
distinct from being dead in Studio itself).

| Phase | State |
|---|---|
| 0 Spikes | Mostly done; a couple items (real PPTX/PDF export live-check, Netskope-host check) deferred/skipped as unneeded |
| 1 Studio backend (Workspace-JWT auth bridge) | **Done, tested** (1,242+ backend tests pass, live smoke passed), pushed to `Dev-Backend` |
| 2 Workspace → Next 16 | **Done**, pushed to `Dev-A` |
| 3 Headless renderer + shared slide-render code | **Done**, pushed to `Dev-Backend`. `STUDIO_RENDER_ONLY=true` flag (off by default) makes Studio's own Next app 404 everything except the renderer |
| 4 Port screens into Workspace | **Done, pushed to `Dev-A`.** `/app/studio/*` routes, `src/app/api/studio/[...path]` proxy, asset-URL rewriting for `/app_data/...`. Superseded in part by the item below: the proxy no longer routes through Studio's own Next.js server at all |
| 5 Trimmed dashboard | **Done, pushed to `Dev-A`.** All/Favorites tabs, sort, grid/list; Studio's sidebar/folders/trash/credits UI removed |
| 6 Sidebar/chat handoff + orchestrator `X-On-Behalf-Of` | **Done, pushed** (`Dev-A` + the orchestrator repo's `Dev-A`) |
| 7 Deployment/cutover | Was deferred; not independently re-verified as done — no `STUDIO_RENDER_ONLY` set anywhere in either repo, and neither `Dev-Backend` nor `Dev-A` is merged into its repo's main line yet |

**Phases 0–6 are complete and pushed** (verified via `git rev-list`: `feature/workspace-identity` is
0 commits ahead/behind `origin/Dev-Backend`; `Dev-A` is fully in sync with `origin/Dev-A`). A further,
real, committed-and-pushed change beyond what Phase 4 originally described: **API calls and
render/export now bypass Studio's own Next.js server entirely.** Workspace UI's
`src/lib/studio-proxy.ts` calls Studio's FastAPI directly rather than through Studio's Next.js
`proxy.ts` middleware (that middleware's `NextResponse.rewrite()` buffering was dropping long-running
requests — a live PPTX export died with `ECONNRESET` through that layer while completing successfully
on FastAPI's own side). Workspace UI also now hosts its own synced `/pdf-maker` route, and FastAPI's
export pipeline (`export_utils.py`, via `NEXT_PUBLIC_URL`) targets that instead of Studio's own
`/pdf-maker`. Net effect: **Studio's Next.js server is not required by the integrated flow at all
today** — its functional role has shrunk to being the source of truth for the render/export code
Workspace's copy is synced from, plus hosting the screens deliberately never ported (`/theme`,
`/community`, `/settings`, `/admin`, Custom Template Studio, `/upload`). See
`STUDIO_IN_WORKSPACE_STATUS.md`'s "Studio's own Next.js bypassed" section for the full detail.

Standing decisions: the headless renderer stays in Studio; Studio trusts the Workspace JWT; decks are
owned via the user's Workspace JWT; unattributed dev decks may be deleted; no PRs opened without the
user asking. See `STUDIO_IN_WORKSPACE_STATUS.md` (GenAI-Workspace root) for the authoritative,
continuously-updated status of this migration — this document covers Studio's own architecture, not
the migration's day-to-day state.

## 9. Current status summary

### 9.1 Backend

Extensively hardened across many sessions (see `CLAUDE.md` for full forensic detail per item — this
is a summary, not a substitute). Representative fixed-bug classes:
- Silent env-precedence bugs in Docker (`KEY=${KEY:-}` making "unset" a real empty string, breaking
  `LLM`/`AZURE_OPENAI_*`, `CAN_CHANGE_KEYS`, `DISABLE_IMAGE_GENERATION` in `docker compose` dev runs).
- An outline-flag idempotency bug (`has_explicit_slide_structure` flipping to `false` on any repeat
  stream call for the same presentation) — fixed by persisting the flag on its own column with a
  data-driven backfill migration for pre-existing rows.
- A held-open DB session across a multi-minute Smart-generation SSE stream (real connection-pool
  exhaustion risk on Postgres/MySQL, latent since this fork has only ever run on SQLite in practice).
- No concurrency cap on headless Chromium spawns, across two independent export code paths — fixed
  with per-process semaphores.
- Multiple real PPTX-corruption bugs in the native chart/table export pipeline (schema-illegal OOXML
  values accepted silently by python-pptx, only caught by opening the file in real PowerPoint).
- Several Smart-mode HTML overflow classes (vertical canvas overflow, horizontal/table overflow, a
  CSS Grid/Flexbox min-width squeeze bug, a global unscoped `<table>` CSS rule leaking into
  LLM-generated tables) — mostly fixed with real-render pixel checks plus deterministic inline-style
  guards, not heuristics alone.

Known **open** items (not fixed, tracked in `CLAUDE.md`): Smart-mode charts can render blank in the
live editor during a fast multi-slide streaming burst (self-healing, root cause identified — no
viewport culling on Smart-mode iframes); exported pie/donut legends can show blank squares for
hollow/border-only swatch categories (suspected permanent closed-source-converter limitation);
`/generation`'s "Generate Standard" button label is misleading — it's still Smart HTML, not the
legacy TemplateV2 path (label-only issue); several past fixes still lack automated test coverage (SSE route handlers,
`presentation_layout_resolver.py`, `pptx_color_extraction.py`).

### 9.2 Frontend

Functionally stable on the live route set (§5.1); a large amount of well-built upstream Presenton
code is present but unreachable from the live e&-configured app (§5.2) — always grep for a route's
literal path string before trusting a `page.tsx` found by name search. One app-wide 500 (a dangling
import from an accidental file deletion in an earlier commit) was found and fixed by restoring the
deleted component verbatim.

### 9.3 Deployment

`docker-compose.yml` defines `production`, `production-gpu`, `development`, `development-gpu`
services, each building from `Dockerfile`/`Dockerfile.dev`. Default dev port is 5001
(`docker compose up --build development`); native (non-Docker) dev runs Next.js on :3000 and FastAPI
on :8000 directly. State persists under `app_data/`. `DATABASE_URL` supports Postgres/MySQL for
production; every deployment this fork has actually run has been SQLite.

## 10. Where to go deeper

- `CLAUDE.md` (repo root) — the full chronological forensic log this document was distilled from;
  read it for exact root-cause traces, exact commit/test counts, and every deferred item's reasoning.
- `SDD-AI-Presentation-Studio_v1.0.md` — the original full solution-design audit: architecture, data
  model, security posture, risk register.
- `STUDIO_IN_WORKSPACE_STATUS.md` (GenAI-Workspace repo root) — live status of the Workspace
  migration described in §8.
- `BUG_REPORT_has_explicit_slide_structure_idempotency.md` — standalone write-up of the bug summarized
  in §9.1.
