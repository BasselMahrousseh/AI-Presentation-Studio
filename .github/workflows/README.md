# GitHub Actions workflows

## Test All Applications (`test-all.yml`)

Runs on pushes and pull requests to `main`, and can be started manually:

- presentation export runtime: downloads and verifies the bundled PPTX/PDF export runtime;
- FastAPI: every pytest test using the Python version and locked dependencies
  declared in `servers/fastapi`.

Studio has no frontend of its own any more: its UI lives in the GenAI Workspace UI.
No test step is allowed to fail silently.

## Run the CI checks locally

Install Node.js 20+, npm, Python 3.11, and `uv`, then run:

```bash
./test-local.sh
```

## Run one test group

### FastAPI

```bash
cd servers/fastapi
uv sync --locked --dev
mkdir -p /tmp/presenton-tests/app-data /tmp/presenton-tests/temp
APP_DATA_DIRECTORY=/tmp/presenton-tests/app-data \
TEMP_DIRECTORY=/tmp/presenton-tests/temp \
DATABASE_URL=sqlite+aiosqlite:////tmp/presenton-tests/test.db \
DISABLE_ANONYMOUS_TRACKING=true \
DISABLE_IMAGE_GENERATION=true \
uv run --locked python -m pytest --verbose --tb=short
```

### Presentation export runtime

```bash
npm ci
npm run sync:presentation-export
npm run check:presentation-export
```
