# Svelte Island Example

This independent downstream application mounts one Svelte editor inside
a Pyganini page. Pyganini owns filesystem routes, rendering, generated URLs, and
bounded request capture. The application owns Svelte, JSON and CSRF
policy, state, Vite, lifecycle cleanup, static serving, and caching.

Requires CPython 3.13 or newer, uv, Node 20.19 or newer, and npm.

```bash
uv sync --locked --python 3.14
npm ci
npm run check
npm run build
uv run pyganini generate
uv run pyganini check
uv run pyganini assets check
```

Run the app and refresh the browser manually after rebuilding:

```bash
uv run uvicorn app.main:app --reload
```

Run local validation:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pyright app tests
uv run pytest
PLAYWRIGHT_BROWSERS_PATH=../.playwright npx playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=../.playwright npm run test:browser
```

The repository-level `../../scripts/check-client-islands.sh` installs one
shared Chromium and validates both examples, including temporary rebuild byte
comparison. Clean every transient product after local qualification:

```bash
rm -rf .venv node_modules .pytest_cache .ruff_cache .mypy_cache .pyright
rm -rf test-results playwright-report ../.playwright
find app assets tests -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
```

The marker, lifecycle events, JSON endpoint, framework choice, and build are
application conventions. There is no Pyganini island API, hydration, client
router, registry, proxy, or automatic browser reload.
