# Pyganini Content Pages

This standalone application combines a declared root page, a declared response
that takes precedence over content, trusted HTML, nested Markdown, and a static
section with layout and middleware but no endpoint. The application owns its
Starlette host, content root, layout state, error logging, and fingerprinted CSS.

```text
uv sync --locked --all-groups --python 3.14
uv run --locked pyganini assets dist
uv run --locked pyganini generate
uv run --locked pyganini check
uv run --locked python -m app.main --check-content
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Visit `/privacy`, `/privacy/part-one`, `/about`, and `/declared`. Editing or adding
files below `content/` changes the next GET/HEAD response without generation or
restart. Start `uv run --locked --python 3.14 python dev.py` to refresh the
browser automatically on content and Jinja saves. Repeat `--reload-path PATH`
for another external file/directory. Invalid live edits fail until repaired;
this example's generic error callback logs the failure and sends a root-layout
500 page. Repairing the content refreshes that page into the valid response.

`app/routes/privacy` owns the static privacy layout and middleware.
`content/privacy` owns the authored body and metadata. No content entries appear
in generated URLs or route inventory. `app.shell.layout` supplies explicit host
URLs and asset paths; content never infers navigation or dependencies.

```text
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy app dev.py ../dev_support.py ../authoring_test_support.py tests
uv run --locked pyright app dev.py ../dev_support.py ../authoring_test_support.py tests
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked pytest -q
```

Use trusted first-party content only. See the
[content guide](../../docs/user/content-pages.md) for limits, canonical URLs,
Markdown behavior, error contracts, and application-owned packaged resources.

The [development guide](../../docs/user/development.md) describes the shared
app-owned supervisor and explicit development-only SSE wiring. The normal
production factory remains separate.
