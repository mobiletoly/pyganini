# Pyganini

Pyganini is a server-first, HTML-first, HTMX-native Python web framework inspired
by Goldr. This pre-v0 package validates a Python-package route tree and typed
route declarations, generates a deterministic Starlette router and typed URL
interface, fingerprints final browser-ready assets, and validates runtime
handler ownership when the generated router is imported. Route-local Jinja
pages, nested layouts, fragments, actions, direct Starlette responses, and
generated URL helpers share the same route graph.
Multiple live owners can also share a typed, request-scoped route-kit
implementation without giving the shared package route identity.

Pyganini supports CPython 3.13 and newer. Install an explicit Pyganini wheel or source
distribution artifact with any compliant Python package installer:

```text
python -m pip install ./dist/pyganini-0.0.0-py3-none-any.whl
python -m pip install ./dist/pyganini-0.0.0.tar.gz
```

Pyganini has not been published to a package index. Artifact production and
publication remain separate owner decisions.

Pyganini depends at runtime on Starlette, Jinja, AnyIO, and
`python-multipart>=0.0.32,<0.0.33`. AnyIO provides the accepted worker-thread
cancellation behavior for synchronous handlers; Starlette owns async form
parsing. The host application owns its ASGI server, middleware, lifespan,
dependencies, validation, upload policy, and deployment. uv is a contributor
tool, not a runtime requirement.

Live route packages may also contain `middleware.py` with one direct,
non-empty `MIDDLEWARE: tuple[Middleware, ...]` binding. Pyganini records the
route-tree marker statically and composes application-owned Starlette
middleware root-to-owner on generated routes. The host retains state,
authentication, dependencies, static files, outer middleware, and errors
outside generated dispatch. Applications may opt into generated-route error
composition with the typed `RouteErrorHandler` callback accepted by the
generated `create_router()` factory. A callback may return the existing
`Page`, `FragmentResponse`, Starlette `Response`, or `None` values. Static root
`error_page_template` and `error_fragment_template` declarations select Jinja
presentation for render values; the default `router` remains unchanged.

## Application layout

A consumer application has this fixed boundary:

```text
pyproject.toml
app/
  __init__.py
  shared/
    __init__.py
    reports/
      __init__.py
      page.jinja
  routes/
    __init__.py
    route.py
    middleware.py
    layout.py
    layout.jinja
    error_page.jinja
    error_fragment.jinja
    page.jinja
    users/
      __init__.py
      route.py
      page.jinja
  _pyganini/
    .pyganini-root
    __init__.py
    asgi.py
    urls.py
assets/
  __init__.py
  build/                      final browser-ready input
  dist/                       fingerprinted managed output
  .pyganini/assets.json          managed cleanup state
  pyganini_assets_gen.py         generated typed lookup
```

Its root `pyproject.toml` contains the only project marker:

```toml
[tool.pyganini]
```

The table is empty. Application code owns `pyproject.toml`, `app/__init__.py`,
and all ordinary code under `app/shared/` and `app/routes/`. Pyganini owns all
non-transient content under `app/_pyganini/`, plus fingerprinted files under
`assets/dist`, `assets/.pyganini/assets.json`, and `assets/pyganini_assets_gen.py`
when `assets/build` is enabled. The application owns the asset package marker,
build input, static mount, cache policy, and deployment. See
[`docs/user/assets.md`](docs/user/assets.md). A bounded rich interaction may
remain application-owned inside a server-rendered page; see
[`docs/user/client-islands.md`](docs/user/client-islands.md) and the
independent [React](examples/react_island) and
[Svelte](examples/svelte_island) examples.
Keep generated files visible to Git and do not edit or add files there by hand.

Each live child under `app/routes` is a Python package. Static directory names
use lowercase Python identifiers and map underscores to URL hyphens.
`by_<param>` creates a dynamic segment. A package can declare its page,
fragments, and actions in `route.py`:

```python
from pyganini import action, fragment_route, route

from .handlers import fragment_table, page, post_save

Route = route(
    page=page,
    template="page.jinja",
    fragments=(fragment_route("/table", fragment_table, template="table.jinja"),),
    actions=(action("POST", "/save", post_save, template="form.jinja"),),
)
```

Only `app/routes/route.py` may also declare the two static generated-error
templates. An ordinary declaration containing only these fields creates no
endpoint:

```python
Route = route(
    error_page_template="error_page.jinja",
    error_fragment_template="error_fragment.jinja",
)
```

Generated 404 and 405 pages use the root layout chain. A page returned after
endpoint selection uses that endpoint's live layout chain, including mounted
ancestry. Error fragments use the root fragment template without layouts. The
application owns the callback's page-versus-fragment and HTMX policy; see
[`docs/user/errors.md`](docs/user/errors.md).

Routes may also declare `RouteNav(label=...)` or `RouteNav(key=...)` and
typed live-owner destinations with `to(...)`. Handlers resolve dynamic labels
through `nav(request)` and pass `Navigation` explicitly to Jinja context.
Pyganini supplies values and request preparation only; breadcrumb, Back, and
other navigation HTML remains application-owned. See
[`docs/user/navigation.md`](docs/user/navigation.md).

The declaration values are `RouteDef`, `FragmentRouteDef`, and `ActionDef`.
Handler contracts can use the typing-only `PageRouteResponse`,
`FragmentRouteResponse`, and `RouteResponse` aliases; concrete low-level
responses remain owned by Starlette.

When multiple live owners need the same implementation, keep the owners in
`app/routes/**/route.py` and bind a typed request-scoped kit:

```python
from starlette.requests import Request

import app.shared.reports as reports
from pyganini import route_kit


def create_reports(request: Request) -> reports.ReportsKit:
    return reports.ReportsKit(title="Reports")


Route = route_kit(
    create=create_reports,
    template_root="shared/reports",
    page=reports.page,
    template="page.jinja",
)
```

Pyganini exports `KitRouteDef[K]`, `KitFragmentRouteDef[K]`, `KitActionDef[K]`,
`route_kit`, `kit_fragment_route`, and `kit_action`. Page, fragment, and
non-captured action handlers receive `(kit, request)`; captured action handlers
receive `(kit, request, body)` or `(kit, request, form)`. Each owner chooses
its URLs and exposed surface. See `docs/user/route-kits.md` for the complete
contract.

Run generation from the application or pass an exact root:

```text
pyganini generate
pyganini check
pyganini generate --app-root /path/to/application
pyganini check --app-root /path/to/application
```

Both commands parse and validate the complete route graph without importing
application modules. `generate` writes missing or stale owned files and removes
obsolete owned output after route validation succeeds. `check` compares the
same expected bytes without writing, creating, or deleting application content.

Inspect the accepted source inventory without requiring generated state:

```text
pyganini routes list
pyganini routes list --json
pyganini routes list --mount contact_directory
pyganini routes layouts
pyganini routes explain /users/42
pyganini routes refs
pyganini routes render-units
```

`routes list` builds the same canonical graph and URL-helper projection, then
reports endpoint and effective-layout rows with application-relative source,
owner, mount, helper, static declaration metadata, navigation, destination,
implementation, mounted-selection, and root error-render evidence. The
`pyganini.routes.v1` JSON payload carries the same structured facts. It does not
import application or generated modules and does not read or write
`app/_pyganini`. See
[`docs/user/route-inspection.md`](docs/user/route-inspection.md) for the table,
`pyganini.routes.v1` JSON schema, filtering, ordering, diagnostics, and later
inspection boundaries. `routes layouts` renders a deterministic ASCII tree at
the final live paths, including effective layouts, pages, fragments, actions,
and complete page/action layout chains. Both commands inspect source only and
leave generated state untouched.

`routes explain` accepts one absolute path or hierarchical absolute URL and
explains its once-decoded ASGI path, method selection, endpoint, parameters,
declaration metadata, implementation binding, source and mounted-owner
evidence, selected layouts, and root error-render boundary. It uses the
canonical graph and generated-dispatch path priority without importing
application or generated modules, executing handlers, or reading
`app/_pyganini`. A matched
explanation writes deterministic ASCII to stdout; a path 404 or method 405
writes its complete diagnostic to stderr with no stdout.

`routes refs` is a separate conservative source inventory for direct HTMX
request attributes in graph-selected `.jinja` files. It uses the canonical
route graph and generated URL-helper spelling without rendering templates or
changing `pyganini check`. See the route-inspection guide for its statuses and
`pyganini.refs.v1` JSON output.

`routes render-units` reports only canonical page, fragment, and action
endpoints with declared templates. It includes retained template source,
mounted-owner evidence, and effective page or action layout chains without
loading Jinja, importing application or generated modules, or reading
`app/_pyganini`. See the route-inspection guide for the `pyganini.render_units.v1`
JSON output and the distinction between declared render capability and runtime
response selection. Root error templates remain outside this endpoint-only
render-unit schema; `routes list` and `routes explain` report them separately.

Each local handler accepts one Starlette `Request`. Mutation actions may
explicitly opt into immutable `Body` or `Form` values from
`pyganini.request_data`; the selected handler then receives `(request, data)`. A
kit creator accepts the request. Page, fragment, and non-captured action
handlers receive `(kit, request)`; captured action handlers receive
`(kit, request, body)` or `(kit, request, form)`. Handlers can return
`Page`,
`FragmentResponse`, or a concrete Starlette `Response` accepted for its route
surface. Pages render through selected `layout.py` and `layout.jinja` pairs;
fragments render without layouts. Import the default generated router after
generation:

```python
from app._pyganini.asgi import router
```

Applications that register Jinja filters, globals, tests, or extensions create
a configured environment and a new generated router:

```python
from app._pyganini.asgi import create_router
from pyganini import create_environment

environment = create_environment()
environment.filters["currency"] = format_currency
router = create_router(environment=environment)
```

Generated URL helpers are imported from the generated module and receive any
mount or proxy prefix explicitly:

```python
from app._pyganini.urls import urls

app_urls = urls.with_base_path(request.scope.get("root_path", ""))
users_path = app_urls.users.path
```

Generated request Navigation binds its canonical trail, current, and Back
hrefs to that same trusted decoded ASGI `root_path`. Applications still bind
generated URL and asset helpers explicitly. Pyganini reads no proxy header and
does not infer deployment prefixes.

Pass `app_urls` explicitly in a page or fragment context when a template needs
it. The interface produces local absolute paths only; it does not build
generic query strings or read request globals. Navigation destination values
add only their declared trail key and bounded local return state. Plain paths
and mounted helpers remain query-free. See
[`docs/user/urls.md`](docs/user/urls.md).

Keep HTMX attributes visible in route-local Jinja and use the same explicit URL
surface for `href`, `action`, and `hx-*` values. `routes refs` can inventory
direct HTMX request attributes, while `pyganini check` remains source and
generated-state validation only. Async form handlers use Starlette's
`request.form()` context manager; `pyganini.request_data` provides the explicit
bounded sync-action boundary; and `from pyganini import hx` provides typed HTMX
request readers and response-header names. See `docs/user/htmx.md` for the
form limits, upload lifetime, validation, and host boundaries.

Applications may also opt into the narrow pyganini.sse helper for typed
Server-Sent Event framing, comments, and Last-Event-ID retrieval. Starlette
continues to own StreamingResponse; the application owns routes, authorization,
replay, cleanup, cache headers, proxy behavior, and deployment. See
docs/user/sse.md.

The router can serve directly or mount under Starlette or FastAPI. Importing it
performs controlled application imports and validates the generated route and
handler evidence before requests are served. Pyganini runs async handlers on the
event loop and sync handlers in an AnyIO worker thread.

## Runnable downstream example

[`examples/full_feature`](examples/full_feature) is a locked contact-directory
application that exercises route-local pages, nested layouts, a shared
contact-directory kit with `/users` and `/settings/users` owners, a dynamic
page, a layout-free fragment, a bounded synchronous multipart action, generated
URL values, visible HTMX behavior, optional `pyganini.csrf`, application-owned
middleware, fingerprinted browser assets, direct Starlette hosting, a FastAPI
mount, navigation breadcrumbs, dynamic contact labels, destinations,
alternate trail selection, Back return safety, and layout-aware page and
fragment error presentation. Its browser suite wraps the complete application
below `/directory` while the ordinary run entry point stays root-mounted. Its README contains the
exact setup, launch, generation, typing, HTTP, and browser commands. The
example does not add a framework server, automatic CSRF enforcement, an asset
compiler, or an application-owned route registry.

## Contributing

The repository uses uv 0.12.3 and Python 3.14 for development while retaining
Python 3.13 compatibility:

```text
uv python install 3.13 3.14
uv lock --check
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy src/pyganini
uv run --locked --python 3.14 pyright src/pyganini
uv run --locked --python 3.14 pytest -q tests/test_csrf_typing.py tests/test_sse_typing.py tests/test_assets.py::test_generated_asset_consumers_are_checked_by_both_type_checkers
uv run --locked --python 3.14 pytest
uv sync --locked --all-groups --python 3.13
uv run --locked --python 3.13 pytest
```

The direct mypy and Pyright commands own strict framework-source analysis.
The focused pytest command proves that both checkers accept valid CSRF, SSE,
and generated-asset consumers and reject their invalid counterparts for the
intended public-signature errors. The complete pytest suites retain all other
typing and runtime evidence on both supported Python lines.

See `docs/user/` for supported usage. Maintainer records live in
`docs/arch/route-graph.md`, `docs/arch/project-package-generation.md`,
`docs/arch/assets.md`,
`docs/arch/generated-asgi-dispatch.md`, `docs/arch/rendering-responses.md`,
`docs/arch/generated-url-interfaces.md`, `docs/arch/route-kits.md`, and
`docs/arch/htmx-async-forms.md`.
