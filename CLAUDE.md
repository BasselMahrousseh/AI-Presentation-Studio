# AI Presentation Studio

Read [AGENTS.md](AGENTS.md) and its architecture-first sequence before executing
setup/build/test/service/migration commands or changing code/configuration.
Initial read-only inspection is allowed to establish context.

Keep this guide under 300 lines. Keep architectural constraints and durable lessons;
use Git history for old sessions and resolved investigations.

## Purpose and architecture

This is the backend behind Presentation Studio in `GenAI-Workspace-UI`. Read
`docs/ARCHITECTURE.md` for the route contract, data model and authentication.
The standalone Studio frontend, local login and TemplateV2 generation are retired.

LLM inference must stay inside the e&-contracted Azure tenant. New integrations
that transmit user content outside that boundary must be off by default and documented.
Do not silently enable external content services.

The Workspace `tools.dev` profile launcher starts Studio FastAPI on port 8002
and Workspace on ports 8000/3000. `NEXT_PUBLIC_URL` must point to the Workspace UI because export renders
its `/pdf-maker` page. `FAST_API_INTERNAL_URL` points the UI proxy to Studio.

Install Python dependencies from `servers/fastapi/pyproject.toml` and `uv.lock`
with `uv sync --locked --dev`. The root npm dependencies support LiteParse and sharp;
`scripts/sync-presentation-export.cjs` installs the prebuilt export runtime.

Workspace JWTs identify users; `STUDIO_SERVICE_API_KEY` authenticates backend handoffs.
Direct launches use the actual `servers/fastapi/.env`; the `tools.dev` launcher
uses its explicitly selected development profile instead. Follow the shared
configuration key reference and never duplicate secrets into documentation.
`tests/unit/test_route_contract.py` pins the Workspace API surface. Update clients
and tests together when changing it. Preserve existing databases and Alembic history,
including migrations that remove old tables.
All active Studio tables and its migration tracker use `GENAI_WORKSPACE_`.
This is Workspace functionality in a separate database, not a standalone
`GENAI_PRESENT_` product. Preserve data through the documented rename migration.

## Generation and export rules

- Smart generation repairs individual invalid slides and preserves a contiguous
  saved prefix for resuming. Do not discard a whole deck on the first layout failure.
- Keep outline and generation limits aligned with the Workspace UI. The content-slide
  limit is 40; fixed e& cover/thank-you slides are additional.
- Outline-driven decks above 20 slides use parallel 10-slide chunks. The first chunk
  supplies the style anchor; shorter or outline-free decks use a single stream.
- Validate layout through a real render. Static HTML inspection can miss flex/grid
  sizing and overflow. `min-width: auto` on children can cause unexpected squeeze.
- The converter supports one border style per box. Prefer uniform borders and a
  separate accent element; mixed border colors or widths may disappear on export.
- `python-pptx` does not validate OOXML. Changes to chart/table XML need a real
  PowerPoint open as well as automated tests. Area-chart `dLblPos` overrides have
  corrupted exported files; leaving the default is the only verified safe behavior.
- A subprocess starting is not proof a server bound its port. Check the listener
  and startup output when diagnosing runtime failures.

## Verification and known limitations

Run `uv run --locked python -m pytest -q` in `servers/fastapi` and
`npm run check:presentation-export` at the repository root. Use temporary application
storage for tests. Linux filesystem permission tests need a Linux environment.

Some hollow legend swatches lose their fill in exported PPTX. The Workspace editor
also does not currently mount the deck chat. Verify the current UI before assuming
API-only features are discoverable.
