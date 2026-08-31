# Kit Routes Example

This focused application mounts one reusable reports subtree below two live
filesystem route owners:

- `/admin/reports` selects the shared page, table fragment, inner layout, and
  `/audit` child.
- `/user/reports` selects the shared page, table fragment, and inner layout,
  but leaves `/audit` out of the live graph.

Each owner creates its own typed `ReportKit`. The kit carries owner-specific
data, policy, and URLs bound from the generated `mount_urls` catalog. The
shared Jinja templates keep their HTMX attributes visible.

## Run the example

From this directory:

```text
uv sync --locked --all-groups --python 3.14
uv run pyganini assets dist
uv run pyganini generate
uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/`, then compare the admin and user report pages.
Changing the period or selecting **Refresh table** requests the owner-specific
table fragment.

## Inspect the mounted source

```text
uv run pyganini routes list
uv run pyganini routes list --mount reports
```

The full inventory contains six live endpoints. The mount-filtered inventory
also shows `/user/reports/audit` as excluded, which explains why that path
returns 404 and has no generated URL member.

## Validate the example

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pyright app tests
uv run pytest
uv run pyganini assets check
uv run pyganini check
```

The application serves its fingerprinted CSS and vendored HTMX runtime from
`assets/dist`. It vendors `htmx.org` `4.0.0-beta6` from the package's
[versioned distribution](https://cdn.jsdelivr.net/npm/htmx.org@4.0.0-beta6/dist/htmx.min.js).
