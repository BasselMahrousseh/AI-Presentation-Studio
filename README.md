# e& Presentation Studio — backend

The presentation-generation backend behind **Presentation Studio** in GenAI-Workspace. It turns a brief
or source documents into a reviewed outline, then into an editable Smart (HTML) slide deck, and exports
it to PowerPoint or PDF. Two deck styles are offered: **Standard** (the model designs freely) and the
**e& template** (fixed e& cover, footer and thank-you slide around generated content).

There is no UI in this repo. Every Studio screen lives in the Workspace UI (`GenAI-Workspace-UI`,
`src/features/studio`), which calls this FastAPI server. Architecture, the full route list and the auth
model are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); working notes are in [`CLAUDE.md`](CLAUDE.md).

## Layout

```text
servers/fastapi/        FastAPI API + database (SQLite by default, Postgres/MySQL via DATABASE_URL)
servers/fastapi/.env    Backend config (Azure OpenAI, image settings, service key)
presentation-export/    Downloaded PPTX/PDF export runtime (gitignored; see below)
resources/              LiteParse document-extraction runner
Dockerfile              FastAPI-only production image
```

## Run locally with Workspace

Use the shared guide in `../GenAI-Workspace/docs/developer-setup.md`. It covers
Python 3.11 for this API, Python 3.12 for Workspace, Node.js 22, the export runtime,
Chromium/fonts, and the optional local Oracle database for Workspace.

After installing the prerequisites, run from `GenAI-Workspace` with its virtualenv Python:

```bash
python -m tools.dev init
python -m tools.dev doctor --profile sqlite --studio
python -m tools.dev start --profile sqlite --studio
```

This starts Studio on port 8002, Workspace on 8000 and the UI on 3000. Studio's
SQLite data stays separate from Workspace's database in both developer profiles.
Use <http://localhost:3000/app/studio>. Real deck generation requires the approved
Azure settings below; mock Workspace chat does not provide a Studio model.

## Configuration

`servers/fastapi/.env` (real environment variables take precedence):

| Variable | Purpose |
| --- | --- |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_MODEL` | The only LLM provider. `LLM` may be unset or `azure`. |
| `DISABLE_IMAGE_GENERATION` | `true` uses placeholders; otherwise `IMAGE_PROVIDER` and its key are required. |
| `STUDIO_SERVICE_API_KEY` | Key the Workspace backend authenticates with (its `PRESENTATION_STUDIO_API_KEY`). |
| `WORKSPACE_JWT_SECRET` | Verifies Workspace users' JWTs. Required unless `DISABLE_AUTH=true` (local dev only). |
| `NEXT_PUBLIC_URL` | Workspace UI origin; export renders its `/pdf-maker` page. |
| `APP_DATA_DIRECTORY`, `DATABASE_URL`, `MIGRATE_DATABASE_ON_STARTUP` | Storage and migrations. |

## Tests

```bash
cd servers/fastapi && uv run --locked python -m pytest -q
```

`tests/unit/test_route_contract.py` pins the exact routes the Workspace uses. `./test-local.sh` runs the
same checks as CI.

## Database migrations

Alembic, run on startup when `MIGRATE_DATABASE_ON_STARTUP=true`, or by hand:

```bash
cd servers/fastapi && APP_DATA_DIRECTORY=app_data uv run alembic upgrade head
```

## Docker

```bash
docker build -t presentation-studio .
docker run -p 8000:8000 --env-file servers/fastapi/.env -e NEXT_PUBLIC_URL=https://<workspace-host> presentation-studio
```

## The e& template

`smart_template: "eand"` makes the backend reserve the fixed title and thank-you positions, give the model
a content safe-area contract, and apply the fixed footer after the generated HTML is validated. The fixed
brand markup is never sent to the model. Layout lives in `servers/fastapi/utils/smart_brand_templates.py`;
the artwork is served by the Workspace UI (`public/smart-templates/eand/`).

## Troubleshooting

| Problem | Check |
| --- | --- |
| Startup fails with an Azure OpenAI error | Azure variables in `servers/fastapi/.env`. |
| Workspace calls return `401` | `WORKSPACE_JWT_SECRET` must equal the Workspace's effective JWT secret. |
| Chat hand-off returns `401`/`403` | `STUDIO_SERVICE_API_KEY` must equal the Workspace's `PRESENTATION_STUDIO_API_KEY`. |
| `LiteParse runner not found` on upload | Run `npm install --omit=dev --ignore-scripts` from the repo root. |
| Export returns `500` / runtime missing | Run `npm run sync:presentation-export`; check `BUILT_PYTHON_MODULE_PATH` and that `NEXT_PUBLIC_URL` reaches the Workspace UI. |

## License

Based on Presenton. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
