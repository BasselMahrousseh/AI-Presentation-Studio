# AVD backend: install, run, and API reference

FastAPI is the API to run inside AVD. It listens only on `http://127.0.0.1:8000`.
The live generation path is Smart HTML: create a deck, stream an outline, then stream slide HTML, then export PPTX.

Base URL for every path below:

```text
http://127.0.0.1:8000
```

After the server is running, Postman can import the live spec:

```text
http://127.0.0.1:8000/openapi.json
```

Interactive docs: `http://127.0.0.1:8000/docs`

## 1. Install and run from a fresh AVD

Install **Python 3.11** and use `pip`. The pins in `servers/fastapi/requirements.txt` were taken from the project lock (`requires-python` is `>=3.11,<3.12`). Python 3.12 and 3.13 are outside that range. Delete `servers/fastapi/.venv` if it was created with another Python version.

### 1.1 Tools to install on the AVD

- Git
- Python 3.11, with `python` and `pip` on PATH (`python --version` must print 3.11.x)
- Node.js 20 or newer (frontend and PPTX export)

### 1.2 Get the code

```powershell
cd C:\Users\Ahmed.Zsayed\Documents\Repos
git clone <internal-repo-url> AI-Presentation-Studio
cd AI-Presentation-Studio
```

If the clone already exists, start from the repository root and pull the branch you deploy internally.

### 1.3 Python environment and backend packages

From `servers\fastapi`, using Python 3.11:

```powershell
cd servers\fastapi
python --version
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe --version
```

`requirements.txt` contains 201 pinned packages, including FastAPI, the model client, database drivers, document parsers, and pytest. The version line must show Python 3.11.x. `.venv` is local and must not be committed. This step needs network access to PyPI, or an internal wheel index.

### 1.4 Backend environment file

Create `servers/fastapi/.env`. Do not commit it.

```dotenv
LLM=azure
AZURE_OPENAI_API_KEY=<internal-key>
AZURE_OPENAI_ENDPOINT=<internal-azure-openai-endpoint>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_OPENAI_API_VERSION=<api-version>
AZURE_OPENAI_MODEL=<model-alias>

APP_DATA_DIRECTORY=app_data
USER_CONFIG_PATH=app_data/userConfig.json
DISABLE_AUTH=true
CAN_CHANGE_KEYS=false
DISABLE_IMAGE_GENERATION=true
```

Use the internal Azure OpenAI endpoint. `DISABLE_AUTH=true` is only for a private Postman smoke test on this AVD. On a shared machine, set `DISABLE_AUTH=false`, create an admin with `POST /api/v1/auth/setup`, then log in. `CAN_CHANGE_KEYS=false` makes `GET` and `PUT /api/v1/admin/provider-settings` return `403`, which is expected when keys live only in `.env`.

### 1.5 Database

From `servers/fastapi`, with the venv active:

```powershell
$env:APP_DATA_DIRECTORY = "app_data"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

With no `DATABASE_URL`, the app uses SQLite under `servers/fastapi/app_data`. For Postgres or MySQL, set `DATABASE_URL` before this command and before starting the server.

### 1.6 Start the API

From `servers/fastapi`:

```powershell
.\.venv\Scripts\Activate.ps1
python server.py --port 8000
```

Leave this terminal open. Check:

```text
GET http://127.0.0.1:8000/api/v1/auth/status
GET http://127.0.0.1:8000/api/v1/auth/llm-status
```

`llm-status` returns `{ "llm_configured": true }` when the Azure variables are complete.

### 1.7 UI and PPTX export

FastAPI can create and stream decks by itself. A real PPTX also needs the Next.js renderer and the export bundle.

From the repository root:

```powershell
npm install --omit=dev --ignore-scripts
node scripts\sync-presentation-export.cjs
```

Create `servers/nextjs/.env.local`:

```dotenv
DISABLE_AUTH=true
CAN_CHANGE_KEYS=false
FAST_API_INTERNAL_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FAST_API=http://127.0.0.1:8000
NEXT_PUBLIC_URL=http://127.0.0.1:3000
APP_DATA_DIRECTORY=C:/Users/Ahmed.Zsayed/Documents/Repos/AI-Presentation-Studio/servers/fastapi/app_data
TEMP_DIRECTORY=C:/Users/Ahmed.Zsayed/Documents/Repos/AI-Presentation-Studio/servers/fastapi/app_data/temp
BUILT_PYTHON_MODULE_PATH=C:/path/to/convert-win32-x64.exe
```

Use absolute Windows paths. `BUILT_PYTHON_MODULE_PATH` must point at an existing `convert-win32-x64.exe`. Restart Next.js after editing this file.

From `servers/nextjs`:

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`.

## 2. How to call the API

### 2.1 Auth

| Mode | What to send |
| --- | --- |
| `DISABLE_AUTH=true` | Nothing. Every `/api` route is open. `/api/v1/auth/status` returns `username: "electron"`, `role: "admin"`. |
| Session cookie | `POST /api/v1/auth/login` sets HttpOnly cookie `presenton_session` (30 days). |
| API key | `Authorization: Bearer sk-presenton-...` from `POST /api/v1/auth/token/create`. Admin only. |
| Workspace JWT | `Authorization: Bearer <jwt>`, or cookie `studio_token`. Workspace users are never admins. |

Public even when auth is on:

- `GET /api/v1/auth/status`
- `GET /api/v1/auth/verify`
- `POST /api/v1/auth/setup`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/ppt/presentation/export/chart-capture`
- `POST /api/v1/ppt/presentation/export/table-capture`
- `OPTIONS` on any path

`/docs`, `/openapi.json`, and `/redoc` require auth when `DISABLE_AUTH` is not set. A database with zero users returns `428` and `{ "detail": "Login setup is required", "setup_required": true }` until `POST /api/v1/auth/setup` runs.

### 2.2 Content types

| Kind | Header |
| --- | --- |
| JSON body | `Content-Type: application/json` |
| File upload | `multipart/form-data` |
| Server-Sent Events | response `Content-Type: text/event-stream` |

SSE frames look like:

```text
event: response
data: {"type":"status","status":"..."}

event: response
data: {"type":"error","detail":"..."}

event: response
data: {"type":"complete","outline":{...}}
```

`type` is one of `status`, `trace`, `error`, `quality_flags`, `complete`. Hold the request open in Postman. Outline and slide streams can run for minutes.

### 2.3 Limits that apply to generation

- Maximum slides: `40`
- Outline item text: `300` words
- Tone: `default`, `casual`, `professional`, `funny`, `educational`, `sales_pitch`
- Verbosity: `concise`, `standard`, `text-heavy`
- Generation mode: `standard` (legacy layout path) or `smart` (live HTML path)
- e& brand id: `smart_template` must be `eand`, and only when `generation_mode` is `smart`
- Presentation versions for list filters: `v1-standard`, `v2-standard`

## 3. Postman sequence for the live deck

This is the path to test first.

### 3.1 Create

`POST /api/v1/ppt/presentation/create`

```json
{
  "content": "Q3 network performance review",
  "n_slides": 3,
  "language": "English",
  "file_paths": null,
  "tone": "professional",
  "verbosity": "standard",
  "instructions": null,
  "include_table_of_contents": false,
  "include_title_slide": true,
  "web_search": false,
  "generation_mode": "smart",
  "community_design_ids": null,
  "smart_template": "eand",
  "smart_brand_colors": null,
  "source_presentation_id": null
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `content` | yes | Brief text. For Smart mode, at least one of `content`, `file_paths`, or `community_design_ids` is required. |
| `n_slides` | no | Integer `1`–`40`. Omit for automatic count. Stored as `0` when omitted. Table of contents requires at least `3`. |
| `language` | no | Stored trimmed. Empty string is allowed. |
| `file_paths` | no | Paths returned by `POST /api/v1/ppt/files/upload` or `/decompose`. Missing files return `404`. |
| `tone` | no | Default `default`. |
| `verbosity` | no | Default `standard`. |
| `instructions` | no | Extra instruction string. |
| `include_table_of_contents` | no | Default `false`. |
| `include_title_slide` | no | Default `true`. |
| `web_search` | no | Default `false`. Keep `false` on AVD unless an internal search provider is configured. |
| `generation_mode` | no | Default `standard`. Use `smart` for the live path. |
| `community_design_ids` | no | Integers. Smart mode only. |
| `smart_template` | no | `eand` or omit. Smart mode only. Colors sent with `eand` are ignored. |
| `smart_brand_colors` | no | Hex colors. Smart mode only, and not for `eand`. |
| `source_presentation_id` | no | UUID of an existing deck. Copies its source files when `file_paths` is empty. |

Response: `200`, `PresentationModel` JSON. Keep `id`.

An unbranded Smart deck uses the same body with `smart_template` omitted.

### 3.2 Stream the outline

`GET /api/v1/ppt/outlines/stream/{id}`

No body. Response is SSE. The `complete` event carries the outline. The server also stores it on the presentation.

### 3.3 Read or replace the outline

`GET /api/v1/ppt/outlines/{id}`

No body. Response `PresentationOutlineModel`. Empty outline is `{ "slides": [] }` when none is stored. `404` if the deck does not exist.

`PUT /api/v1/ppt/outlines/{id}`

```json
{
  "slides": [
    { "content": "Network availability by region" },
    { "content": "Incidents and customer impact" },
    { "content": "Actions for the next quarter" }
  ]
}
```

Response is the same outline. This sets `n_slides` to the slide count and derives `title` from the outline.

### 3.4 Stream the slides

`GET /api/v1/ppt/presentation/stream/{id}`

No body. For `generation_mode: "smart"` this starts slide generation directly. The legacy standard path returns `400` until `POST /prepare` has stored a structure and the outline is non-empty.

Response is SSE. The final `complete` event key is `presentation` and the value is `PresentationWithSlides`.

### 3.5 Read the deck

`GET /api/v1/ppt/presentation/{id}`

Response `PresentationWithSlides`: `id`, `content`, `n_slides`, `language`, `title`, `created_at`, `updated_at`, `tone`, `verbosity`, `slides`, `generation_mode`, `type`, `smart_template`, `generation_status` (`in_progress` or `completed`), `is_favorite`, generation ids.

Each slide includes `id`, `presentation`, `layout_group`, `layout`, `index`, `content`, `html_content`, `speaker_note`, `properties`, `ui`.

### 3.6 Export

`POST /api/v1/ppt/presentation/{id}/export`

```json
{ "export_as": "pptx" }
```

`export_as` is `pptx` or `pdf`. Response:

```json
{ "presentation_id": "<uuid>", "path": "/app_data/..." }
```

This needs Next.js at `NEXT_PUBLIC_URL` and the presentation-export bundle. Failure text `presentation-export runtime is not available` means section 1.7 was skipped.

## 4. Full endpoint catalog

Paths are complete. `{id}` and other braces are path parameters.

### 4.1 Auth — prefix `/api/v1/auth`

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| GET | `/api/v1/auth/status` | none | `{ configured, authenticated, username, user_id, role }` |
| GET | `/api/v1/auth/llm-status` | none | `{ "llm_configured": true \| false }` |
| GET | `/api/v1/auth/verify` | Optional header `x-original-uri` for asset checks | `{ authenticated, user fields, method }` or `401` |
| POST | `/api/v1/auth/setup` | `{ "username": "admin1", "password": "at-least-8" }` | First admin only. Username `3`–`128` chars, no spaces. `409` if an account exists. Does not log in. |
| POST | `/api/v1/auth/login` | `{ "username": "admin1", "password": "..." }` | Password `6`–`128` on login. Sets `presenton_session`. `428` if setup was never run. `429` after repeated failures. |
| POST | `/api/v1/auth/logout` | none | `{ "success": true }` and clears the cookie |
| GET | `/api/v1/auth/token/list` | none | Admin. List of `{ token, user_id, created_at }` |
| POST | `/api/v1/auth/token/create` | none | Admin. Returns a new `sk-presenton-...` token |
| POST | `/api/v1/auth/token/revoke` | `{ "token": "sk-presenton-..." }` | Admin. `{ "message": "Token revoked" }` or `404` |
| GET | `/api/v1/auth/presenton/status` | none | Presenton Cloud connection status. Skip on internal AVD. |
| POST | `/api/v1/auth/presenton/logout` | none | Clears the Presenton Cloud provider. Admin. |
| POST | `/api/v1/auth/presenton/device/start` | `{ "device_name": "optional, max 120" }` | Starts a device-code login to Presenton Cloud. Admin. |
| POST | `/api/v1/auth/presenton/device/poll` | `{ "device_code": "16 to 512 chars" }` | Polls that device login. Admin. |

### 4.2 Presentations — prefix `/api/v1/ppt/presentation`

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| GET | `/all` | Query: `version` (`v1-standard` or `v2-standard`), `include_slides` (default `true`), `sort_by` (`created_at` or `updated_at`), `favorites_only` (default `false`), `include_unfinished` (default `false`) | `PresentationWithSlides[]`, newest first |
| GET | `/{id}` | none | One deck with slides, or `404` |
| PATCH | `/{id}/favorite` | `{ "is_favorite": true }` | `{ "id", "is_favorite" }`. Does not change `updated_at`. |
| DELETE | `/{id}` | none | `204`. `404` if missing or owned by someone else. |
| POST | `/{id}/duplicate` | none | `PresentationWithSlides` copy |
| POST | `/create` | See section 3.1 | New presentation row |
| POST | `/create/blank` | none | `201`. One empty slide titled `Untitled Presentation`, language `English` |
| POST | `/prepare` | See body below | `{ "presentation_id" }`. Legacy layout path used before a non-smart stream. |
| GET | `/stream/{id}` | none | SSE slide generation |
| PATCH | `/update` | `{ "id": "<uuid>", "n_slides": 5, "title": "Title", "theme": {}, "slides": [] }` | All fields except `id` are optional. Sending `slides` replaces every slide on the deck. |
| PATCH | `/slide_update` | `{ "slide": { "id", "presentation", "layout_group", "layout", "index", "content", "html_content", "speaker_note", "properties", "ui" } }` | Updated `SlideModel`. `id` and `presentation` must match the stored slide. `index` is not overwritten. |
| POST | `/edit` | `{ "presentation_id": "<uuid>", "slides": [{ "index": 0, "content": {} }], "export_as": "pptx" }` | Updates matching slides by `index`, then exports. Response `{ presentation_id, path, edit_path }`. |
| POST | `/derive` | Same body as `/edit` | Copies the deck, applies the same slide updates, exports the copy. |
| POST | `/{id}/export` | `{ "export_as": "pptx" }` | `{ presentation_id, path }` |
| POST | `/export/chart-capture` | `{ "token": "<server token>", "presentation_id": "<uuid or null>", "charts": [] }` | `{ "success": true }`. Public. Max `200` charts and about 2 MB. `413` if larger. |
| POST | `/export/upgrade-charts` | `{ "token", "presentation_id", "pptx_path" }` | Authenticated. `pptx_path` must be a `.pptx` under `app_data/exports`. |
| POST | `/export/table-capture` | `{ "token", "presentation_id", "tables": [] }` | `{ "success": true }`. Public. Max `200` tables, `500` cells each, about 2 MB. |
| POST | `/export/upgrade-tables` | `{ "token", "presentation_id", "pptx_path" }` | Authenticated. Call after chart upgrade on the same file. |

`POST /prepare` body:

```json
{
  "presentation_id": "<uuid>",
  "outlines": [{ "content": "Slide markdown" }],
  "layout": "general",
  "title": "Optional title"
}
```

`outlines` must be non-empty and at most `40` items. `layout` is a built-in template name (`momentum`, `dynamic`, `executive`, `general`, `modern`, `standard`, `swift`, when present) or a custom template id. Unknown templates return `400`.

### 4.3 Outlines — prefix `/api/v1/ppt/outlines`

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| GET | `/{id}` | none | Stored outline, or `{ "slides": [] }` |
| PUT | `/{id}` | `{ "slides": [{ "content": "..." }] }` | Saves outline and title |
| POST | `/{id}/quality-flags/acknowledge` | `{ "group_keys": ["filename.pdf::image_only"] }` | `{ "acknowledged_quality_flag_groups": [] }` |
| GET | `/stream/{id}` | none | SSE outline generation |

`group_keys` come from SSE `quality_flags` groups. Each key is `{source_file}::{status}` where status is `partial` or `image_only`.

### 4.4 Slide edit — prefix `/api/v1/ppt/slide`

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| POST | `/edit` | `{ "id": "<slide uuid>", "prompt": "Make the second bullet shorter" }` | Legacy JSON slide. Returns the slide with a **new** `id`. `404` if the slide or deck is missing. |
| POST | `/edit-html` | `{ "id": "<slide uuid>", "prompt": "Tighten the headline", "html": null }` | Smart HTML edit. `html` is optional and defaults to the stored `html_content`. `400` if both are empty. |

`/edit-html` is the live single-slide regenerate call.

### 4.5 Files — prefix `/api/v1/ppt/files`

| Method | Path | Form fields | Success |
| --- | --- | --- | --- |
| POST | `/upload` | `files`: one or more files, field name `files` | JSON array of temp file paths. `400` if none. Max `100` MB each. |
| POST | `/decompose` | JSON `{ "file_paths": ["<path from upload>"], "language": "English" }` | `[{ "name", "file_path" }]`. `language` is optional. |
| POST | `/update` | multipart: text `file_path`, file `file` | `{ "message": "File updated successfully" }` |

Accepted upload types: `.pdf`, `.txt`, `.doc`, `.docx`, `.docm`, `.odt`, `.rtf`, `.ppt`, `.pptx`, `.pptm`, `.odp`, `.xls`, `.xlsx`, `.xlsm`, `.ods`, `.csv`, `.tsv`. PDF and Office extraction need the root `npm install` from section 1.7.

Use the decompose `file_path` values as `file_paths` on `POST /presentation/create`.

### 4.6 Images — prefix `/api/v1/ppt/images`

| Method | Path | Query / body | Success |
| --- | --- | --- | --- |
| GET | `/search` | `query` (required), `limit` `1`–`30` (default `12`), `provider` (`pexels` or `pixabay`), `strict_api_key` (default `false`). Optional header `X-Provider-Api-Key`. | URL strings. `401` in strict mode when the key is missing. |
| GET | `/generate` | `prompt` | Generated image URL, or the provider payload. Needs an image provider. |
| GET | `/generated` | none | Assets with `id`, `created_at`, `is_uploaded`, `path`, `extras`, `file_url` |
| POST | `/upload` | multipart file field `file` | Same asset object, `is_uploaded: true` |
| GET | `/uploaded` | none | Uploaded assets |
| DELETE | `/{id}` | none | `204` |

Stock search and generated images call external image providers. Leave them unused on AVD unless those providers are approved. `DISABLE_IMAGE_GENERATION=true` blocks generation.

### 4.7 Icons, fonts, themes

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| GET | `/api/v1/ppt/icons/search` | `query` (required), `limit` (default `20`), `icon_type` or `icon_weight` | Icon name strings |
| POST | `/api/v1/ppt/fonts/upload` | multipart font file | `{ success, font_name, font_url, font_path, message }` |
| GET | `/api/v1/ppt/fonts/list` | none | `{ success, fonts, message }` |
| GET | `/api/v1/ppt/fonts/uploaded` | none | `{ "fonts": [] }` |
| DELETE | `/api/v1/ppt/fonts/delete/{filename}` | none | Deletes that uploaded font |
| GET | `/api/v1/ppt/themes/default` | none | `[]` in this fork. Built-in themes are served by the Next.js app. |
| GET | `/api/v1/ppt/themes/all` | none | Saved custom themes |
| POST | `/api/v1/ppt/themes/create` | `{ "name", "description", "company_name", "logo", "logo_url", "data" }` | `ThemeResponse`. `logo` must be an uploaded image UUID when set. |
| PATCH | `/api/v1/ppt/themes/update/{theme_id}` | Same fields, all optional | Updated theme |
| DELETE | `/api/v1/ppt/themes/delete/{theme_id}` | none | `204` |
| POST | `/api/v1/ppt/theme/generate` | `{ "primary", "background", "accent_1", "accent_2", "text_1", "text_2" }` | All fields optional color strings. Response is a computed `ThemeData` palette. |

Font extensions: `.eot`, `.fntdata`, `.otf`, `.ttc`, `.ttf`, `.woff`, `.woff2`.

### 4.8 Chat — prefix `/api/v1/ppt/chat`

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| GET | `/conversations` | `presentation_id` UUID | `{ conversation_id, updated_at, last_message_preview }[]` |
| GET | `/history` | `presentation_id`, `conversation_id` | `{ presentation_id, conversation_id, messages: [{ role, content, created_at }] }` |
| DELETE | `/conversation` | `presentation_id`, `conversation_id` | `204` |
| POST | `/message` | See JSON below | `{ conversation_id, response, tool_calls }` |
| POST | `/message/stream` | Same JSON | SSE |

```json
{
  "presentation_id": "<uuid>",
  "presentation_type": "smart",
  "message": "Shorten slide 2",
  "conversation_id": null,
  "attachments": [
    {
      "type": "document",
      "name": "notes.pdf",
      "file_path": "<temp path>",
      "mime_type": "application/pdf"
    }
  ]
}
```

`message` is `1`–`8000` characters. `presentation_type` is `standard` or `smart` (default `standard`; send `smart` for live decks). `conversation_id` empty starts a thread. At most `8` attachments. Extra JSON fields are rejected.

### 4.9 Feedback — prefix `/api/v1/ppt/feedback`

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| GET | `/{presentation_id}` | none | `{ outline_generation_id, deck_generation_id, outline, deck }` |
| PUT | `/{presentation_id}/{stage}` | See JSON below | `stage` is `outline` or `deck`. `409` if `generation_id` is not the current one. |

```json
{
  "generation_id": "<uuid from the deck>",
  "rating": 1,
  "reasons": [],
  "comment": null
}
```

`rating` is `1` (up) or `-1` (down). `comment` max `1000` characters. Down-vote `reasons` for `outline`: `off_topic`, `missing_key_points`, `wrong_structure`, `too_shallow`, `wrong_slide_count`, `language_tone`, `other`. For `deck`: `poor_design`, `inaccurate_content`, `too_much_text`, `bad_images`, `ignored_outline`, `broken_formatting`, `other`. Unknown reasons return `422`. At most `10` reasons.

### 4.10 Templates — prefix `/api/v1/ppt/template`

Custom Template Studio. Not part of the e& Smart generation path.

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| GET | `/all` | none | Template list |
| POST | `/init` | `{ "pptx_url", "slide_image_urls": [], "fonts": {}, "name", "description", "icon_type" }` | `201`. Starts a template from an uploaded PPTX. |
| POST | `/async` | Same body as `/init` | `201`. Background task. Poll `/api/v1/async-tasks/status/{id}`. |
| POST | `/fonts-upload-and-slides-preview` | upload fields used by the template UI | Font check and slide preview |
| POST | `/extract-color-palette` | PPTX upload / URL payload used by the template UI | Color palette |
| POST | `/layouts/generate` | `{ "template_id", "prompt" }` | One generated slide layout. `prompt` `1`–`8000` chars. `template_id` alias `id` is accepted. |
| POST | `/layouts/create` | `{ "template_id", "index": 0 }` or `{ "template_id", "indices": [0, 1] }` | One of `index` or `indices` is required. Indices unique and `>= 0`. |
| POST | `/generate-blocks` | `{ "template_id" }` (`id` alias accepted) | Template with generated blocks |
| PATCH | `/{template_id}/layouts` | Slide layout patch items | Updated template |
| PATCH | `/{template_id}` | `{ "name", "description", "layout_count", "thumbnail", "is_default", "layouts", "fonts", "icon_type" }` | Metadata update. All fields optional. |
| GET | `/{template_id}` | none | One template |
| DELETE | `/{template_id}` | none | `204` |

### 4.11 Community — prefix `/api/v1/ppt/community/presentations`

These call the community catalog. Leave them unused when the AVD has no route to that service.

| Method | Path | Query | Success |
| --- | --- | --- | --- |
| GET | `` | `page` (default `1`), `page_size` (`1`–`24`, default `8`), `created_at_gt`, `created_at_lt`, `views`, `views_gt`, `views_lt`, `likes`, `likes_gt`, `likes_lt`, `order_by` (`created_at`, `views`, `likes`, `priority`), `order` (`asc` or `desc`) | Catalog page object |
| GET | `/{community_id}` | path integer `>= 1` | One community deck |

### 4.12 Provider probes — do not use on AVD

These exist so the settings screen can list remote models. They send the key you put in the body to that vendor.

| Method | Path | Body |
| --- | --- | --- |
| POST | `/api/v1/ppt/openai/models/available` | `{ "url": "https://...", "api_key": "..." }` |
| POST | `/api/v1/ppt/anthropic/models/available` | `{ "api_key": "..." }` |
| POST | `/api/v1/ppt/google/models/available` | `{ "api_key": "..." }` |
| GET | `/api/v1/ppt/ollama/models/supported` | none |
| GET | `/api/v1/ppt/ollama/models/available` | Query `ollama_url` optional |
| GET | `/api/v1/ppt/ollama/models/library` | none |
| POST | `/api/v1/ppt/ollama/models/pull` | Query `model_name`, optional `ollama_url` |
| POST | `/api/v1/ppt/codex/auth/initiate` | none |
| GET | `/api/v1/ppt/codex/auth/status/{session_id}` | none |
| POST | `/api/v1/ppt/codex/auth/exchange` | code exchange body for Codex OAuth |
| POST | `/api/v1/ppt/codex/auth/refresh` | none |
| GET | `/api/v1/ppt/codex/auth/status` | none |
| POST | `/api/v1/ppt/codex/auth/logout` | none |

### 4.13 Admin — prefix `/api/v1/admin`

Requires an admin session. With `DISABLE_AUTH=true`, the caller is treated as admin.

| Method | Path | Body / query | Success |
| --- | --- | --- | --- |
| GET | `/provider-settings` | none | Current provider config. `403` when `CAN_CHANGE_KEYS=false`. |
| PUT | `/provider-settings` | JSON object of provider keys | Saved settings. Same `403` when keys are locked. |
| GET | `/users` | none | `{ id, username, role, created_at }[]` |
| POST | `/users` | `{ "username", "password" }` | `201`. Username rules match `/auth/setup`. Password min `8`. |
| PUT | `/users/{user_id}/password` | `{ "password": "at-least-8" }` | Updated public user |
| DELETE | `/users/{user_id}` | none | `204` |
| GET | `/feedback` | `stage` (`outline` or `deck`), `format` (`json` or `csv`, default `json`), `offset` (default `0`), `limit` (`1`–`1000`, default `100`) | JSON summary plus page, or a CSV file |

### 4.14 Async tasks — prefix `/api/v1/async-tasks`

Used by template creation, not by Smart deck generation.

| Method | Path | Query | Success |
| --- | --- | --- | --- |
| GET | `` | `type`, `status`, `created_at` or `created_at_from`, `created_at_to`, `order_by` (`created_at` or `updated_at`), `order` (`asc` or `desc`), `limit` (`1`–`200`, default `50`), `offset` (default `0`) | Task rows |
| GET | `/status/{id}` | none | One task, or `404` |

### 4.15 Webhooks — prefix `/api/v1/webhook`

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| POST | `/subscribe` | `{ "url": "https://internal-listener", "secret": "optional", "event": "presentation.generation.completed" }` | `201` `{ "id" }`. `event` is `presentation.generation.completed` or `presentation.generation.failed`. |
| DELETE | `/unsubscribe` | `{ "id": "<subscription id>" }` | `204`. `404` if missing. |

### 4.16 Mock — prefix `/api/v1/mock`

Fixed sample payloads. No model call and no database write.

| Method | Path | Success |
| --- | --- | --- |
| GET | `/presentation-generation-completed` | A fake `{ presentation_id, path, edit_path }` list |
| GET | `/presentation-generation-failed` | A fake `{ status_code: 500, detail }` list |

## 5. Static files

| Path | What it serves |
| --- | --- |
| `/app_data/...` | Generated files, uploads, exports. Most of this tree requires auth. `/app_data/fonts/` and `/app_data/templates/` stay public. |
| `/static/...` | Bundled fonts, icons, and vendor assets when the `static` directory exists. |

## 6. What a failed call usually means

| Status | Meaning |
| --- | --- |
| `400` | Validation: slide count, missing Smart prompt, bad template, empty file upload, bad export path |
| `401` | Auth is on and the cookie, API key, or Workspace JWT is missing or invalid |
| `403` | Admin-only route, or provider settings while `CAN_CHANGE_KEYS=false` |
| `404` | Deck, slide, template, or file path is missing. Another user's deck looks like `404`. |
| `409` | Setup already done, or feedback `generation_id` is stale |
| `413` | Chart or table capture payload is over the cap |
| `422` | Body shape is wrong, or a feedback reason is not in the allowed list |
| `428` | No user exists yet. Call `POST /api/v1/auth/setup`. |
| `429` | Login rate limit. Honor `Retry-After`. |
| `500` | Server error. Read the FastAPI terminal. Export `500` often means the Next.js renderer or `convert-win32-x64.exe` is missing. |
