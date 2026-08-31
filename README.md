# e& Presentation Studio

An AI presentation workspace built on Presenton. Create an editable slide deck from a brief, then export it to PowerPoint. Alongside regular Smart Mode, the app provides a dedicated **e& Smart Mode** that applies the supplied e& corporate design without asking the model to recreate it.

## Features

- Generate presentations from a short prompt, source documents, or web research.
- Edit generated slides in the browser and export finished decks.
- Use **Generate presentation** for regular Smart Mode, or **Generate with e& template** for the separate branded workflow.
- Preserve the e& title artwork, logo, footer, confidentiality labels, gradient, and thank-you slide as fixed application assets rather than model-generated content.

## e& Smart Mode

The e& button creates a fixed deck structure:

| Position | Source | Result |
| --- | --- | --- |
| 1 | Fixed title slide | Supplied e& title design, populated with the generated deck title. |
| 2-4 | AI | Smart Mode content constrained above the fixed e& footer. |
| 5 | Fixed thank-you slide | Supplied e& thank-you design. |

The default request contains five slides, so the model creates three middle content slides. The e& flow requires at least three slides: title, content, and thank-you. Normal Smart Mode remains unchanged.

```text
servers/fastapi/utils/smart_brand_templates.py  Brand shells and fixed slides
servers/nextjs/public/smart-templates/eand/     Supplied e& image assets
servers/nextjs/app/frontend/index.tsx            Separate e& generate button
```

## Project structure

```text
servers/
|- nextjs/       Next.js 16 + React frontend (port 3000)
`- fastapi/      FastAPI generation API and database (port 8000)

presentation-export/  HTML-to-PPTX export support
templates/            Presentation template definitions
```

## Local setup (Windows)

### Prerequisites

- Node.js 20+
- Python 3.11
- Git
- An OpenAI API key or another supported LLM-provider configuration

### 1. Configure FastAPI

Create or update `servers/fastapi/.env`. Do not commit this file.

```dotenv
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1
APP_DATA_DIRECTORY=app_data
```

### 2. Start the backend

From the repository root:

```powershell
cd servers\fastapi
uv sync --group dev
.\.venv\Scripts\Activate.ps1
uv run python server.py --port 8000  
```

`uv sync --group dev` installs the locked Python dependencies and creates `.venv`. If needed, install uv with `pip install uv`. Keep this terminal running.

### 3. Configure the Next.js runtime

Create `servers/nextjs/.env.local`. Next.js loads this file when it starts, so restart `npm run dev` after adding or changing it.

```dotenv
# Local development only. Do not use DISABLE_AUTH in a shared deployment.
DISABLE_AUTH=true
CAN_CHANGE_KEYS=false
FAST_API_INTERNAL_URL=http://127.0.0.1:8000
NEXT_PUBLIC_FAST_API=http://127.0.0.1:8000
NEXT_PUBLIC_URL=http://127.0.0.1:3000

# Use absolute paths on Windows. The converter is required for PPTX export.
BUILT_PYTHON_MODULE_PATH=C:/path/to/convert-win32-x64.exe
APP_DATA_DIRECTORY=C:/path/to/project/servers/fastapi/app_data
TEMP_DIRECTORY=C:/path/to/project/servers/fastapi/app_data/temp
```

Keep `CAN_CHANGE_KEYS` aligned with FastAPI. When it is `false`, the frontend does not request editable provider settings; a direct `/api/user-config` request correctly returns `403`.

### 4. Install the document-extraction runtime

PDF and document uploads use LiteParse through a small Node.js runner. Install the root runtime dependencies from the repository root:

```powershell
npm install --omit=dev --ignore-scripts
```

The runner is stored at `resources/document-extraction/liteparse_runner.mjs` and FastAPI detects it automatically. Restart FastAPI after installing dependencies or changing its environment.

### 5. Install the PPTX export runtime

From the repository root, download the pinned presentation-export package:

```powershell
node scripts\sync-presentation-export.cjs
```

Verify a previously installed runtime with:

```powershell
node scripts\sync-presentation-export.cjs --check-only
```

The export route reports `presentation-export runtime is not available` when this step has not been completed. On Windows, also ensure `BUILT_PYTHON_MODULE_PATH` points to an existing `convert-win32-x64.exe`.

### 6. Start the frontend

Open another terminal from the repository root:

```powershell
cd servers\nextjs
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The custom frontend calls FastAPI at `http://127.0.0.1:8000`, so both services must be running.

## How the e& template is protected

The frontend sends `smart_template: "eand"` only when the e& button is used. The backend validates that template ID, reserves the fixed title and thank-you positions, gives the model a content safe-area contract, and applies the fixed footer only after generated HTML has been validated. The source PPTX, converted JSON, and fixed brand markup are not sent to the model.

To change supplied artwork, replace the corresponding files under `servers/nextjs/public/smart-templates/eand/` without changing their filenames. If the layout changes too, update `servers/fastapi/utils/smart_brand_templates.py`. Generate a new deck afterwards; saved decks are not changed retroactively.

## Database migrations

Run this after pulling backend schema changes:

```powershell
cd servers\fastapi
$env:APP_DATA_DIRECTORY = "app_data"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The e& workflow stores `smart_template` on a presentation. If the API reports that this column does not exist, the migration was run against a different database directory. Run the command above from this clone and restart FastAPI.

## Docker

```powershell
docker compose up --build development
```

Set LLM variables such as `OPENAI_API_KEY` and `OPENAI_MODEL` before starting Docker. The development service uses port 5001 by default and persists state under `app_data/`.

## Tests

```powershell
# Focused e& and Smart Mode backend tests
cd servers\fastapi
.\.venv\Scripts\python.exe -m pytest tests/unit/test_smart_brand_templates.py tests/unit/test_smart_presentation_generation.py

# Frontend linting
cd ..\nextjs
npm run lint

# Repository-level template converter tests (from repository root)
npm test
```

## Troubleshooting

| Problem | Check |
| --- | --- |
| Generation cannot start | FastAPI must be running at `127.0.0.1:8000`. |
| `smart_template` database-column error | Run the migration with `APP_DATA_DIRECTORY=app_data`, then restart FastAPI. |
| An old deck has no e& title/footer/closing slide | Generate a new deck; brand slides are applied during generation. |
| e& artwork does not load | Verify `servers/nextjs/public/smart-templates/eand/` and restart Next.js after asset changes. |
| Model/API error | Check the API key and model values in `servers/fastapi/.env`. |
| `/api/user-config` returns `403` | Set the same `CAN_CHANGE_KEYS` value in `servers/nextjs/.env.local` and `servers/fastapi/.env`, then restart both services. A `403` is expected when the value is `false`. |
| `LiteParse runner not found` when uploading a PDF | Run `npm install --omit=dev --ignore-scripts` from the repository root, confirm `resources/document-extraction/liteparse_runner.mjs` exists, then restart FastAPI. |
| `presentation-export runtime is not available` or PPTX export returns `500` | From the repository root, run `node scripts\\sync-presentation-export.cjs`; then verify the Windows converter configured by `BUILT_PYTHON_MODULE_PATH` exists. |
| Editing or regenerating a slide reports `socket hang up` | The failure is in FastAPI's LLM-backed `/api/v1/ppt/slide/edit-html` request. Check the FastAPI terminal traceback, then verify its provider endpoint, deployment/model name, and API credential. |

## License

See [LICENSE](LICENSE) and [NOTICE](NOTICE).
