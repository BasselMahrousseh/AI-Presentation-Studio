# Presentation Studio backend

## Read architecture before executing

Developers and AI agents must read the [documentation index](../GenAI-Workspace/docs/README.md),
[system architecture](../GenAI-Workspace/docs/architecture.md),
[database and migrations](../GenAI-Workspace/docs/database.md), and
[configuration contract](../GenAI-Workspace/docs/configuration.md) before running setup,
installation, build, test, service, migration or deployment commands, or changing
code/configuration. Read the guide for the affected component next. Initial
read-only inspection of files and Git status is allowed to establish context.
Follow [AGENTS.md](AGENTS.md); resolve documented prerequisites before executing.

Studio turns briefs/source documents into reviewed outlines, editable Smart HTML decks and PowerPoint/PDF exports. Standard and e& branded decks share the Smart generation path. Screens live in `GenAI-Workspace-UI`; this repository runs FastAPI and export tooling.

Read the [Studio architecture](docs/ARCHITECTURE.md), [Workspace architecture](../GenAI-Workspace/docs/architecture.md), [database guide](../GenAI-Workspace/docs/database.md) and [developer setup](../GenAI-Workspace/docs/developer-setup.md). The architecture distinguishes actual behavior from missing authentication, rendering, egress and scaling safeguards.

## Local development

Use separate Python environments: **3.11** here and **3.12** for Workspace. The workstation baseline is Node.js **22**. Studio also needs the pinned export runtime, Chromium, fonts and parser tools in developer setup.

From this repository:

```text
npm ci --ignore-scripts
npm run sync:presentation-export
npm run check:presentation-export
cd servers/fastapi
uv sync --locked --dev --python 3.11
```

Then run from `GenAI-Workspace` with its virtualenv Python:

```text
python -m tools.dev init
python -m tools.dev doctor --profile sqlite --studio
python -m tools.dev start --profile sqlite --studio
```

Before starting Studio, configure approved Azure credentials, API version and endpoint/base URL in the selected profile. Empty values fail startup; Workspace mock chat does not supply a Studio model. Generation also needs a valid deployment/model. The launcher starts Studio on 8002, Workspace on 8000 and the UI on 3000. Open [Presentation Studio](http://localhost:3000/app/studio).

## Configuration and database

Maintain Studio's actual service configuration in `servers/fastapi/.env`. The default Workspace local launcher also reads that file for Studio settings; explicitly selected `.env.dev.sqlite` or `.env.dev.oracle` profiles are self-contained and do not fall back to it. The [loader](servers/fastapi/utils/environment.py) honors `STUDIO_ENV_FILE`; an empty selector prevents file loading. Implicit `.env` loading is development-only. Local secret files are ignored and must be supplied on a fresh clone. Use the [configuration key reference](../GenAI-Workspace/docs/configuration.md#supported-key-reference-and-validation) and inject deployment secrets.

- Studio's Azure environment is independent of Workspace Admin settings.
- `WORKSPACE_JWT_SECRET` verifies supported Workspace user tokens. `STUDIO_SERVICE_API_KEY` matches Workspace's `PRESENTATION_STUDIO_API_KEY`. Read the architecture before selecting SSO.
- `NEXT_PUBLIC_URL` must reach the Workspace UI/base path from Studio for `/pdf-maker`. The UI's `FAST_API_INTERNAL_URL` points back to FastAPI.
- The shared deployment uses Oracle with a **dedicated Studio schema owner**, alongside Workspace's owner in the same approved PDB. Set `PERSISTENCE_MODE=oracle`, leave `DATABASE_URL` empty and supply Studio's own `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_DSN`. An explicit `DATABASE_URL` overrides the selector; local profiles deliberately keep Studio SQLite.
- Set `ARTIFACT_STORAGE_BACKEND=s3` and configure private `ARTIFACT_S3_*` storage. Studio adds `/studio/` to its prefix and serves owner-authorized `/app_data/` references. `APP_DATA_DIRECTORY` is local staging; it must sit outside `TEMP_DIRECTORY`. Filesystem remains available for development.
- Keep image generation disabled and external search unconfigured until an approved integration is selected.

All active Studio application tables use `GENAI_WORKSPACE_` because Studio is
part of Workspace. `GENAI_PRESENT_` is reserved for a future unrelated standalone
presentation application and is not used here. Studio owns a separate schema and
transaction boundary; its migration tracker is `GENAI_WORKSPACE_STUDIO_SCHEMA_VERSION`.

The [central Oracle package](../GenAI-Workspace/db/genai-workspace/oracle/README.md) contains checked SQL for both owners, provisioning order and data-copy commands. The [migration guide](docs/ARCHITECTURE.md#migrations-and-ownership-cutover) covers Alembic, ownership and SQLite-to-S3/Oracle cutover. Existing data requires explicit file and row migration; configuration changes do not migrate it. Oracle startup validates the installed schema and never calls `create_all`.

## Verification and deployment

From `servers/fastapi`:

```text
uv run --locked python -m pytest -q
```

[Route tests](servers/fastapi/tests/unit/test_route_contract.py) pin the Workspace API. `npm run check:presentation-export` at repository root checks/patches installed runtime files. Model calls, rendering, restore and PowerPoint compatibility need integration validation.

The [Dockerfile](Dockerfile) creates an API-only image on port 8000. It currently uses Node 20; test parity with the Node 22 workstation setup. Follow [deployment guidance](docs/ARCHITECTURE.md#configuration-and-prerequisites) for private routing, authentication, durable volumes, CORS and capacity. Image build success does not establish production readiness.

Based on Presenton. See [LICENSE](servers/fastapi/LICENSE) and [NOTICE](servers/fastapi/NOTICE).
