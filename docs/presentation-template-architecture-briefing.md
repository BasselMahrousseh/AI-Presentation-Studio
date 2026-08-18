# Presentation and template architecture briefing

This is a code-based briefing for the current Next.js + FastAPI implementation. It covers the standard Presentation V2 flow and the custom Template V2 flow that the current UI uses.

## The short version

- Next.js owns the browser UI and routes. FastAPI owns generation, persistence, exports, and served assets.
- Presentations are persisted in `presentations`; their individual slides are persisted in `slides`. Both use UUIDs.
- Custom and built-in templates use the same `template_v2` table. The `is_default` flag distinguishes built-ins (`true`) from custom templates (`false`).
- Custom-template creation is asynchronous. `async_tasks` holds its durable task state and progress. The client polls the task-status endpoint.
- Presentation streaming is different: `/presentation?…&stream=true` opens a Server-Sent Events (SSE) connection which emits generated slide data as it becomes available.
- Generated files/images live under the configured application-data directory and are served by FastAPI under `/app_data`. Database rows store their paths/URLs and structured presentation/template JSON.

## System map

```text
Browser (Next.js)
  |  getApiUrl('/api/v1/...') -- same-origin via nginx in web/Docker
  v
FastAPI API
  |-- SQLAlchemy/SQLModel --> DB (SQLite by default; PostgreSQL/MySQL supported)
  |-- app-data directory --> /app_data static mount (images, uploads, exports, fonts)
  |-- LLM/image providers --> generated slide text, layouts, and assets
  `-- export service --> PPTX/PDF output
```

`getApiUrl` normally uses same-origin API paths in a browser, allowing nginx to proxy to FastAPI. In Electron or with an explicit `fastapiUrl` query override it can call FastAPI directly. One important exception in the current root UI is `app/frontend/index.tsx`, which calls `http://127.0.0.1:8000/api/v1/ppt/presentation/generate` directly; that is a local-development assumption and should be replaced with `getApiUrl(...)` for deployment portability.

## Where presentation IDs, information, and images come from

### IDs and structured presentation data

| Item | Source of truth | Key fields |
| --- | --- | --- |
| Presentation | `presentations` / `PresentationModel` | UUID `id`, owner, prompt/content, title, outline, selected layout/structure, fonts, settings, timestamps |
| Slide | `slides` / `SlideModel` | UUID `id`, parent `presentation` UUID, `index`, layout identifiers, generated `content`, optional `html_content`, UI data |
| Custom/built-in template | `template_v2` / `TemplateV2` | string UUID `id`, owner, name/description, raw layouts, generated layouts/components, assets, `is_default` |
| Async job | `async_tasks` / `AsyncTaskModel` | `task-<random hex>` ID, type, status, message, JSON progress data/error |
| Image asset | `imageasset` / `ImageAsset` | UUID, owner, path, uploaded/generated flag, extra metadata |

`PresentationModel` and `SlideModel` have an `owner_id`; application-level SQLAlchemy criteria scope their reads to the current authenticated owner. Built-in `TemplateV2` rows are intentionally shared: a user can read a template if it is theirs, or if it has `owner_id = NULL` and `is_default = true`.

### Images, fonts, uploads, and exported PPTX/PDF files

- FastAPI’s `ImageGenerationService` writes generated images into `get_images_directory()`, which resolves to the configured application-data directory’s `images` folder.
- `ImageAsset` rows keep generated/uploaded asset paths and metadata. Slide content/UI also contains URLs that refer to those assets.
- Uploads, fonts, images, and exports are stored in application-data subfolders (`uploads`, `fonts`, `images`, and `exports`). FastAPI mounts this directory as `/app_data`; static bundled assets are mounted as `/static`.
- Next.js runs `normalizeBackendAssetUrls` when it receives presentation/template data. It converts backend file paths (including `/app_data/...`) into URLs that work in the current browser/runtime.
- PPTX template uploads first produce a modified PPTX URL plus slide preview-image URLs. The custom-template task stores those URLs in `TemplateV2.assets` along with the generated layouts and font map.

Database configuration is `DATABASE_URL` when set. Without it, the default is SQLite at `<APP_DATA_DIRECTORY>/fastapi.db` (or `/tmp/presenton/fastapi.db` if no application-data directory is configured). PostgreSQL and MySQL are also supported through SQLAlchemy’s async drivers.

### Local-development configuration in this workspace

When FastAPI is launched through `servers/fastapi/server.py`, it explicitly loads `servers/fastapi/.env`. That local file currently sets `APP_DATA_DIRECTORY` to `C:\Users\JoshuaS\Documents\presenton-main (1)\presenton-main\app_data`, so that is the active application-data location for that launch path. `DATABASE_URL` is not set there, so FastAPI uses SQLite at that directory’s `fastapi.db`.

The repository-root `app_data` directory is the Docker volume source and may also be used by another local launcher, but it is not automatically selected by `server.py` while the current `.env` value is present. If FastAPI is started directly with `uvicorn api.main:app`, confirm that the launcher loads the same `.env` or exports these variables; `api/main.py` imports dotenv but does not itself call `load_dotenv`.

The root `start.js` launcher is a separate case. It requires `APP_DATA_DIRECTORY` in the parent process environment and passes that exact environment to **both** the FastAPI child (port 8000) and the Next.js child (port 3000). `server.py` loads `.env` with python-dotenv's normal non-overriding behavior, so an inherited `APP_DATA_DIRECTORY` wins over the value in `servers/fastapi/.env`. Next.js has no independent browser-side app-data setting: its server-only routes and bundled export helper inherit the same variable from `start.js` (or use a repo-root `app_data` fallback in a few export helpers).

## How `/presentation?id=<id>` loads a deck

1. `app/(presentation-generator)/presentation/page.tsx` reads the `id` query parameter with `useSearchParams()` and passes it to `PresentationPage`.
2. `PresentationPage` calls `usePresentationData` unless the route is in stream mode.
3. `usePresentationData.fetchUserSlides()` calls `DashboardApi.getPresentation(id)`.
4. `DashboardApi.getPresentation` sends:

   ```http
   GET /api/v1/ppt/presentation/{id}
   ```

5. FastAPI loads one `PresentationModel` and all `SlideModel` rows whose `presentation` foreign key equals the supplied UUID, ordered by `SlideModel.index`.
6. The response is normalized, loaded into the Redux `presentationGeneration` slice, custom fonts are loaded, and the editor renders `SlideContent` from the returned slide records.

The handler is `servers/fastapi/api/v1/ppt/endpoints/presentation.py:get_presentation`. It returns `PresentationWithSlides` containing presentation metadata, fonts, and the full slide list.

## Presentation generation flow

There are two supported paths in the codebase.

### Guided editor flow: create → outline → prepare → SSE slide generation

```text
POST /presentation/create
  -> creates a PresentationModel with a UUID
POST /outlines/... (stream/generate)
  -> creates/revises outlines
POST /presentation/prepare
  -> persists reviewed outlines, resolves the selected TemplateV2 layout,
     chooses slide-layout structure and fonts
GET /presentation/stream/{presentationId}  [SSE]
  -> generates/persists slides and emits incremental response events
GET /presentation/{presentationId}
  -> later reloads the saved deck and all slide rows
```

`/presentation/stream/{id}` is an SSE endpoint. The browser creates an `EventSource`, receives `response` events/chunks, updates Redux as slides arrive, and finally has persisted slides available for normal `GET /presentation/{id}` loads.

### Direct generation API flow

```text
POST /api/v1/ppt/presentation/generate
  -> validates the request and template
  -> generates outline, structure, slide content, and assets
  -> writes PresentationModel + SlideModel + ImageAsset rows
  -> exports PPTX/PDF
  -> returns the generated presentation ID and edit path
```

The root frontend currently uses this direct synchronous endpoint and then navigates to `/presentation?id={presentation_id}`. The input model is `GeneratePresentationRequest`: content, optional slide count, language, tone, instructions, files, and `template`, among other options.

There is also `POST /api/v1/ppt/presentation/generate/async`, which creates an `AsyncTaskModel` of type `presentation.generate` and runs the same generation work in FastAPI background tasks. Its status is available at either the generic task endpoint or `/api/v1/ppt/presentation/status/{taskId}`.

## Custom template creation flow

```text
PPTX selected in Next.js custom-template UI
  -> POST /template/fonts-check and/or font upload/preview endpoints
  -> preview response gives modified PPTX URL, slide-image URLs, and font map
  -> user supplies name + description
  -> POST /api/v1/ppt/template/async
  -> AsyncTaskModel(type='template.create', status='pending') is persisted
  -> FastAPI BackgroundTasks generates a structured layout for each slide
  -> TemplateV2 is persisted with is_default=false
  -> task becomes completed (or error)
```

The current Next.js page sends this payload to `POST /api/v1/ppt/template/async`:

```json
{
  "pptx_url": "...",
  "slide_image_urls": ["..."],
  "fonts": { "...": "..." },
  "name": "...",
  "description": "..."
}
```

The backend parses the PPTX into raw layouts, generates component-aware slide layouts (in parallel where permitted), merges reusable components, and stores the result in one `TemplateV2` record:

- `raw_layouts`: PPTX-derived source layout data
- `layouts`: generated typed slide layouts used to create presentations
- `merged_components`/`components`: reusable design components
- `assets`: PPTX URL, slide image URLs, fonts, extracted images, thumbnail and layout indexes
- `is_default = false`: marks it as a private custom template

## The async-task endpoint: what it tracks

Yes. The endpoint in the question:

```http
GET /api/v1/async-tasks/status/task-7d9b...
```

looks up a row in `async_tasks` by task ID. For a custom-template job it is the authoritative persisted progress record, not merely an in-memory progress indicator.

For `type = "template.create"`, the response exposes:

- `status`: `pending`, `completed`, or `error`
- `message`: e.g. queued, generating slide layouts, completed, or failed
- `data.created_layouts` and `data.remaining_layouts`: the inputs used for the percentage UI
- `data.name` and `data.thumbnail`: enough information to render a pending-template card
- `error`: structured API error data when the job failed
- timestamps

The custom-template page now polls this endpoint every 1.5 seconds while its “Creating template…” screen is shown. The template list can also call `GET /api/v1/async-tasks?type=template.create&status=pending&...` and polls it every 30 seconds to show progress cards.

Important implementation detail: FastAPI `BackgroundTasks` runs in the FastAPI process after the request response. It is adequate for the current local/single-process setup, but it is not a durable distributed work queue. For multi-instance production deployment, use a shared worker/queue system (for example Celery, Dramatiq, RQ, or a cloud queue) while retaining `async_tasks` as the job-status table.

## Endpoint cheat sheet

| Purpose | Method and endpoint | Used by |
| --- | --- | --- |
| List dashboard presentations | `GET /api/v1/ppt/presentation/all?version=v2-standard` | `DashboardApi.getPresentations` |
| Load one saved deck | `GET /api/v1/ppt/presentation/{id}` | `/presentation?id=...` through `DashboardApi.getPresentation` |
| Delete / duplicate deck | `DELETE /api/v1/ppt/presentation/{id}`; `POST /api/v1/ppt/presentation/{id}/duplicate` | dashboard |
| Start guided deck | `POST /api/v1/ppt/presentation/create` | upload/outline flow |
| Persist reviewed outline/template selection | `POST /api/v1/ppt/presentation/prepare` | outline flow |
| Stream slide creation | `GET /api/v1/ppt/presentation/stream/{id}` (SSE) | presentation editor in `stream=true` mode |
| Generate a deck directly | `POST /api/v1/ppt/presentation/generate` | current root frontend |
| Generate a deck asynchronously | `POST /api/v1/ppt/presentation/generate/async` | API clients/integrations |
| List templates | `GET /api/v1/ppt/template/all?default=true|false` | template picker and templates page |
| Get template detail | `GET /api/v1/ppt/template/{templateId}` | template consumers/editor |
| Create a custom template | `POST /api/v1/ppt/template/async` | custom-template page |
| Get task status | `GET /api/v1/async-tasks/status/{taskId}` | custom-template creation loader |
| List pending template jobs | `GET /api/v1/async-tasks?type=template.create&status=pending...` | template list progress cards |
| Edit/delete custom template | `PATCH` / `DELETE /api/v1/ppt/template/{templateId}` | template UI; built-ins are blocked |

All FastAPI presentation/template routers sit under `/api/v1/ppt`; the generic task router is directly under `/api/v1/async-tasks`.

## How to make a custom template a built-in template

There is no current end-user or admin API that promotes an existing custom `TemplateV2` row to a built-in one. This is deliberate in the current model: built-ins are shared and read-only, while custom templates are owned by one user.

The supported built-in workflow is:

1. Put an approved template package in `servers/fastapi/templates/<stable-name>/`.
2. Include its `template.json` (with a stable template ID, layouts, components, assets metadata) and its `static/` assets.
3. On FastAPI startup, `import_default_templates_on_startup()` imports/updates the package into `template_v2`, copies static assets to `<APP_DATA_DIRECTORY>/templates/<template-id>/static`, and sets `is_default = true`.
4. The template becomes globally readable and is excluded from normal custom-template write/delete operations. `_require_private_template` returns HTTP 403 for edits/deletes of built-ins.

For a controlled admin-only “promote existing custom template” feature, implement a privileged backend operation that validates the template, removes/handles its private ownership correctly, packages/copies referenced assets into the built-in static location, and sets `is_default = true`. A direct database update of only `is_default` is not sufficient as a product workflow: it can expose a user-owned template and leave assets outside the managed built-in package.

## Moving to PostgreSQL and object storage

These are complementary changes: PostgreSQL should hold relational/JSON metadata; object storage should hold binary files. Do not put generated PPTX files or image binaries in PostgreSQL.

### PostgreSQL

PostgreSQL is already supported by the database URL code. Set this in the FastAPI runtime environment (for the local `server.py` launch, that means `servers/fastapi/.env`):

```env
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>?sslmode=require
MIGRATE_DATABASE_ON_STARTUP=true
```

The application converts a `postgresql://` URL to `postgresql+asyncpg://` at runtime; Alembic uses a compatible synchronous psycopg URL for migrations. Before switching production traffic:

1. Back up the SQLite `fastapi.db` file and the entire current application-data directory.
2. Provision an empty PostgreSQL database and least-privilege application user.
3. Run Alembic migrations against PostgreSQL (`MIGRATE_DATABASE_ON_STARTUP=true` is the existing deployment setting, though a CI/CD migration step is safer for production).
4. Migrate the SQLite data into PostgreSQL with a tested migration script/tool, preserving UUID/string IDs and JSON columns. Validate row counts and representative presentation/template loads.
5. Point every FastAPI instance at the same PostgreSQL `DATABASE_URL`; do not leave one instance on SQLite.
6. Keep the asset migration separate: database rows contain metadata and asset references, while files remain in application-data until object storage is introduced.

### Object storage (S3, Cloudflare R2, GCS, Azure Blob, etc.)

Object storage is **not** currently configured. The repository includes `boto3`, but the active asset pipeline writes/reads local files using `APP_DATA_DIRECTORY` and FastAPI mounts that directory at `/app_data`. The custom-template preview module even documents that it is adapted for local app-data storage instead of S3.

The safe implementation is to introduce one storage interface, with a local implementation first and an object-store implementation second:

```text
AssetStorage
  put_file(local_path, object_key) -> stored key
  get_to_local(object_key, local_path) -> local file for converters/exporters
  public_or_signed_url(object_key) -> browser URL
  delete(object_key)
```

Use stable tenant-scoped keys such as:

```text
users/<owner-id>/images/<asset-id>.png
users/<owner-id>/exports/<presentation-id>/<export-id>.pptx
users/<owner-id>/uploads/<upload-id>/<filename>
templates/<template-id>/static/<asset-name>
```

Required code changes:

1. Add object-storage settings, e.g. provider, bucket, region/endpoint, credentials, and optional public/CDN base URL. Keep credentials server-side only.
2. Keep a local temporary working directory: PPTX conversion, rendering, and export code needs filesystem paths. Upload final artifacts to object storage after generation; download objects to a temporary file when a library requires a path.
3. Replace direct application-data persistence for generated images, uploads, fonts, exports, and built-in-template static copies with the storage interface. `ImageAsset.path` and JSON asset references should store object keys, not machine-specific absolute paths.
4. Replace `/app_data` static serving for private assets with authenticated download endpoints or short-lived presigned URLs. Public static built-in assets can use a CDN/public bucket prefix if desired.
5. Update `normalizeBackendAssetUrls` and `resolveBackendAssetUrl` so object keys become signed/CDN URLs rather than `/app_data/...` paths.
6. Upload existing `app_data` files, then rewrite every stored path reference: `imageasset.path`, template `assets`, slide content/UI JSON, font records, and any export paths.
7. Verify authorization by attempting cross-user asset access, then add lifecycle/retention rules for temporary uploads and old exports.

Recommended order: move to PostgreSQL first, keep one known application-data folder during stabilization, then add object storage behind the adapter and migrate asset references. This avoids changing the relational data layer and every binary-file path in one release.

## Questions a senior engineer may ask

### Why do we have both a task-status endpoint and presentation SSE?

They solve different UX needs. The template process is a background job whose result is a completed `TemplateV2` record, so the UI polls a persisted task. Presentation streaming needs partial slide payloads immediately so the editor can render individual slides while they are generated; SSE delivers those chunks. Async presentation generation can also use `async_tasks` when an API client only needs eventual completion.

### How is a custom template separated from a built-in one and from another user’s templates?

The same `TemplateV2` schema is used. `is_default=false` means custom; it receives the current request’s `owner_id`. ORM read filtering allows a user to see their own rows plus globally shared rows where `owner_id` is null and `is_default=true`. Built-ins are also protected from normal edit/delete routes.

### What exactly does the template task progress percentage measure?

It measures generated slide layouts, not a time estimate. The backend updates `created_layouts` and `remaining_layouts` as each PPTX-derived slide layout completes. The templates-page card calculates a percentage from those counters and caps it before final completion.

### Is task progress durable across a refresh?

Yes, assuming the database persists. The task row is in `async_tasks`, so a new browser session can query it by task ID or list pending `template.create` tasks. The work itself is currently executed by FastAPI `BackgroundTasks`, however, so process restart durability is not equivalent to a true external job queue.

### How does the browser know which backend to call?

Most Next.js code calls `getApiUrl`, which uses same-origin API paths in browser deployments and lets nginx proxy them. Direct FastAPI access is used for Electron/query overrides. The hard-coded loopback call in the root frontend is an exception worth fixing before non-local deployment.

### Are actual images stored in the presentation row?

Not generally as binary data. The presentation and slides store JSON/text plus image references. Generated/uploaded files are stored in application-data folders and may have `ImageAsset` metadata rows. FastAPI serves their paths, and Next.js normalizes those paths into browser-safe URLs.

### What is the minimum data needed to reopen a presentation?

The presentation UUID. `GET /presentation/{id}` returns the persisted presentation metadata and every ordered slide row. The editor then restores Redux state, fonts, and references to the associated assets.

## Relevant source locations

- Next.js presentation route: `servers/nextjs/app/(presentation-generator)/presentation/page.tsx`
- Presentation load hook/API: `servers/nextjs/app/(presentation-generator)/presentation/hooks/usePresentationData.ts`, `servers/nextjs/app/(presentation-generator)/services/api/dashboard.ts`
- Presentation streaming hook: `servers/nextjs/app/(presentation-generator)/presentation/hooks/usePresentationStreaming.ts`
- Custom-template UI: `servers/nextjs/app/(presentation-generator)/custom-template/CustomTemplatePage.tsx`
- Template client API: `servers/nextjs/app/(presentation-generator)/services/api/template.ts`
- Presentation FastAPI handlers: `servers/fastapi/api/v1/ppt/endpoints/presentation.py`
- Template FastAPI handlers: `servers/fastapi/api/v1/ppt/endpoints/template.py`
- Generic task API: `servers/fastapi/api/v1/async_tasks/router.py`
- SQL models: `servers/fastapi/models/sql/presentation.py`, `slide.py`, `template_v2.py`, `async_task.py`, and `image_asset.py`
- Database/tenant filtering: `servers/fastapi/services/database.py`
- Built-in importer: `servers/fastapi/templates/default_templates.py`
