# AI-Presentation-Studio

## Working with this user

The user is an MIS (Management Information Systems) student with some coding ability but limited background in software engineering, APIs, and LLMs — and wants to actually learn these concepts over time, not just get them hidden. When explaining technical concepts, findings, or decisions, keep it plain and systematic — one or two sentences per point rather than long technical prose — but still introduce and briefly explain the relevant term or concept rather than skipping it entirely.

## Origin

This repo is a fork of the open-source presentation generator from **presenton.ai** — the Next.js `package.json` name is still `presenton`, and much of the generic branding/module naming traces back to that upstream project. The team is incrementally layering custom features and branding (an "e&"/Etisalat-branded smart-deck mode, UI reskins, etc.) on top of that inherited base rather than building from scratch. When something looks orphaned, duplicated, or inconsistently named, check whether it's inherited upstream functionality that predates the e&-specific work before assuming it's a local bug.

Working branch: `restructured-v3-branch`, created off `restructured-v3`. See pinned memory for the git workflow rule (never commit/push directly to `restructured-v3`).

## Architecture

Two servers: `servers/fastapi` (backend, :8000) and `servers/nextjs` (frontend, :3000), talked to by the browser through `proxy.ts` (a Next.js "Proxy," the v16 rename of middleware) which rewrites `/api/v1/*` and `/api/v2/*` to FastAPI.

**Two parallel slide-content models — know which one you're in before changing generation code:**
- **TemplateV2 (structured)**: slides are JSON — a `content` object plus a `ui` element tree (`text`, `image`, `chart`, `table`, `text-list`, `flex`, `grid`, ...), schema-constrained per layout. Bundled templates live at repo-root `/templates/*/template.json`, seeded into the `template_v2` SQL table on startup. Rendered via `lib/template-v2-json-to-html.ts` (flat HTML) or a Konva canvas editor (`components/slide-editor/*`) for drag/resize editing. This is the **"standard"** generation path (`stream_presentation`, `?type=standard`) — each slide is its own sequential LLM call, so it genuinely streams slide-by-slide.
- **Smart HTML (raw)**: the LLM outputs a Tailwind `<section>` fragment per slide directly, rendered via `SmartHtmlSlide.tsx`'s iframe + browser-side Tailwind runtime (`lib/tailwind-browser.ts`). No schema, no structured editor — editing happens via the in-editor AI chat rewriting raw HTML (feature exists but its toggle button is commented out in `PresentationHeader.tsx`, so it's not discoverable). This is the **"smart"** path (`_stream_smart_presentation`, `?type=smart`) — for reasoning models the whole deck is typically one LLM call that "thinks" silently for a long stretch, then emits all slides in a fast burst. The e& brand template (`smart_brand_templates.py`) is *not* a TemplateV2 template — it's hardcoded literal HTML strings spliced around LLM-generated content.

**SSE streaming**: `proxy.ts`'s `NextResponse.rewrite()` silently buffers SSE responses (confirmed via direct backend testing — real per-slide gaps at the source, one burst through the browser). The three stream paths (`/api/v1/ppt/presentation/stream/`, `/api/v2/ppt/presentation/stream/`, `/api/v1/ppt/outlines/stream/`) are excluded from that rewrite and instead hit dedicated Route Handlers (`app/api/v1/.../stream/[id]/route.ts`, via `lib/sse-proxy.ts`) that pipe the FastAPI response through untouched. If a new SSE endpoint is ever added, it needs the same treatment or it will silently stop streaming in real time.

**Auth**: session cookie + `sk-presenton-*` API-key bearer tokens, one role bit (`is_superuser`). When `DISABLE_AUTH` is set, the middleware bypasses auth entirely and `/api/v1/auth/status` hardcodes `username: "electron", role: "admin"` — this is a generic single-user bypass mode, not literally tied to the Electron app (which no longer exists in this fork, see below).

**Async jobs**: `AsyncTaskModel` is genuinely used for template creation (polled by the frontend). The equivalent async wrapper for presentation generation (`/generate/async`, `/status/{id}`) is confirmed dead code — nothing in the frontend calls it; the SSE streaming endpoints are what's actually used.

**Export**: FastAPI never renders PPTX/PDF itself — `services/export_task_service.py` shells out to the `presentation-export/` prebuilt Node bundle as a subprocess (Puppeteer-based). That bundle needs the repo-root `node_modules` installed (specifically `sharp`) — **`npm install` at the repo root** (not just `servers/nextjs`) is required and is not mentioned in README's setup steps. If PPTX/PDF export fails with `Cannot find module 'sharp'`, this is why.

**Electron was removed** from this fork in commit `5d4665f` ("Removed electron," ~Aug 22). Vestiges remain and are currently broken/stale, not yet cleaned up:
- `Dockerfile` and `Dockerfile.dev` both still `COPY electron/resources/...` — a from-scratch Docker build currently fails at that step.
- `.github/workflows/electron-linux-ubuntu22.yml` still tries to build the removed `electron/` directory.
- Frontend Electron-detection code (`isElectronRuntime()`, `window.electron?.exportPresentation`) still exists throughout the Next.js app but is now vestigial — nothing ever sets `window.electron`.

## Session backlog (prune as items are done — don't let this go stale)

From an end-of-session review, priority-ordered per UX/UI-first preference:

1. **Add a "regenerate this slide" action.** Backend already has per-slide retry-with-feedback infrastructure used internally during generation; nothing exposes it after the fact. Pairs naturally with the layout-overflow validator below.
2. **Reconcile the pre-first-slide loading UI.** The header progress pill now shows real backend stage text, but the big center modal shown before the first slide arrives still runs the old elapsed-time fake percentage (`components/ui/progress-bar.tsx`) — inconsistent (real text next to a fake number). Either tie it to real progress once `total_slides` is known, or replace it with something that doesn't imply false precision.
3. **Surface the AI click-to-edit feature.** It's fully wired for smart-mode decks but its header toggle button is commented out — the most useful recovery path for a broken slide is currently undiscoverable.
4. **Improve export failure messaging.** Currently a generic "Export failed" toast; worth checking whether failure modes beyond the `sharp` crash are similarly opaque.
5. **Charts/graphs in exported PPTX** (explicitly deferred by the user to a future session, scope it carefully): TemplateV2 already has a first-class schema-driven `chart` element type (11 chart types) that's a more natural fit for a real editable PPTX chart object. Smart-mode renders charts as live Chart.js canvases — converting a rendered canvas into an editable (not flattened-to-image) PPTX chart is the harder version of this problem. Clarify which path is in scope before starting.
6. **Project health, lower priority**: fix the broken Electron `COPY` lines in both Dockerfiles; add the root `npm install` step to README's setup instructions; delete or document the dead `/generate/async` presentation endpoint; add test coverage for this session's new code (SSE route handlers, `smart_slide_layout.py`'s overflow heuristic, the sidebar-selection-sync fix) — none of it has automated tests yet, only manual/live verification.
