# Navigation Example

This application shows how one generated route graph supplies canonical
breadcrumbs, dynamic labels, destination-selected trails, and semantic Back
links. The Jinja root layout renders every navigation value explicitly.

The example has two owner hierarchies:

- HQ resolves `HQ Team` and `Contoso Retail`.
- Regional resolves `Seattle`, `Regional Team`, and `Northwind Supply`.

Both hierarchies mount the same analytics and customer-report sources. Live
owners provide data, generated URLs, and alternate trail builders.

## Run the example

From this directory:

```text
uv sync --locked --all-groups --python 3.14
uv run pyganini assets dist
uv run pyganini generate
uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/`.

## HQ journeys

Start at `/main/hq/teams/hq-team`.

1. Open **Analytics workflow**.
2. Apply `risk=high` and `page=2`.
3. Open **Contoso Retail report**.
4. Confirm the trail passes through Analytics and Contoso Retail.
5. Follow Back to the filtered analytics URL.

Return to HQ Team, open **Contoso Retail**, then compare:

- **Customer report subtree** keeps the canonical customer ancestry and adds
  the mounted report layout.
- **Shared report destination** uses the `hq-customer` trail to reconstruct
  the HQ entry path at `/main/reports/contoso`.

## Regional journeys

Start at `/main/regional/offices/sea/teams/regional-team` and repeat the two
flows with Northwind Supply. The analytics destination selects
`regional-analytics`; the shared report selects `regional-customer`. Neither
trail contains HQ labels.

## Inspect and validate

```text
uv run pyganini routes list
uv run pyganini routes list --mount analytics
uv run pyganini routes list --mount customer_report
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pyright app tests
uv run pytest
uv run pyganini assets check
uv run pyganini check
```

The example stores data in immutable in-process values. It does not implement
authentication, persistence, browser-history tracking, or proxy-header
inference. A host supplies `root_path`; the FastAPI test mounts the application
at `/directory` and checks prefixed breadcrumbs, destinations, assets, and Back.
