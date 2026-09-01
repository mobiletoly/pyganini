<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/pyganini-logo-dark.svg">
    <img src="docs/assets/pyganini-logo-light.svg" alt="Pyganini violin and snake logo" width="112">
  </picture>
</p>

# Pyganini

[![CI](https://github.com/mobiletoly/pyganini/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mobiletoly/pyganini/actions/workflows/ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/mobiletoly/pyganini?sort=semver)](https://github.com/mobiletoly/pyganini/releases/latest)
[![License](https://img.shields.io/github/license/mobiletoly/pyganini?logo=apache&label=License)](LICENSE)

**If Pyganini saves you time, please consider starring ⭐ the repository - it
helps more developers find it.**

Pyganini is a server-first Python web framework for HTML applications. You
organize routes as Python packages, render Jinja templates, and use generated
URL helpers instead of handwritten paths. Pyganini supports visible HTMX
interactions while your application keeps control of Starlette or FastAPI,
middleware, data access, and deployment.

## Why Pyganini?

Server-rendered applications often accumulate route tables, string URLs, and
rendering conventions that drift apart. Pyganini derives those surfaces from
one filesystem route tree.

- Route packages keep handlers, templates, layouts, and middleware together.
- Generation produces a deterministic Starlette router and typed URL helpers.
- `pyganini check` catches stale generated files and invalid route source.
- Jinja stays focused on HTML, including visible `hx-*` attributes.
- Your application owns its server, middleware, sessions, persistence, and
  deployment policy.

Pyganini supports CPython 3.13 and newer.

## Try a Complete App First

The [full-feature example](examples/full_feature) is a contact directory with
nested layouts, dynamic pages, forms, HTMX fragments, route kits, navigation,
assets, browser helpers, and generated error pages.

```text
git clone https://github.com/mobiletoly/pyganini.git
cd pyganini/examples/full_feature
uv sync --locked --all-groups --python 3.14
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Quick Start

This small application serves one page through an application-owned Starlette
host. Install Pyganini, Starlette, and Uvicorn in a new directory:

```text
mkdir hello-pyganini
cd hello-pyganini
mkdir -p app/routes
touch app/__init__.py app/routes/__init__.py
```

Create `pyproject.toml`:

```toml
[project]
name = "hello-pyganini"
version = "0.0.0"
requires-python = ">=3.13"
dependencies = [
    "pyganini==0.1.1",
    "starlette>=1.6.0,<1.7",
    "uvicorn>=0.52.4,<0.53",
]

[tool.pyganini]
```

Add the root route in `app/routes/route.py`:

```python
from pyganini import route

from .handlers import page

Route = route(page=page, template="page.jinja")
```

Return a page from `app/routes/handlers.py`:

```python
from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls


def page(_: Request) -> Page:
    return Page(
        context={"home_url": urls.root.path},
        metadata=PageMetadata(title="Hello from Pyganini"),
        layout={"product": "Pyganini"},
    )
```

Add `app/routes/page.jinja`:

```html
<main>
  <h1>Hello from Pyganini</h1>
  <p>The generated URL for this page is <code>{{ home_url }}</code>.</p>
</main>
```

Create an empty layout marker at `app/routes/layout.py`, then add
`app/routes/layout.jinja`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{{ metadata.title }}</title>
  </head>
  <body>
    <header>{{ layout.product }}</header>
    {{ child }}
  </body>
</html>
```

Mount the generated router from `app/main.py`:

```python
from starlette.applications import Starlette
from starlette.routing import Mount

from app._pyganini.asgi import router

app = Starlette(routes=[Mount("/", app=router)])
```

Generate the router and URL helpers before importing `app.main`, then check and
run the application:

```text
uv sync
uv run pyganini generate
uv run pyganini check
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Continue with
[Getting Started](docs/user/getting-started.md) to add a dynamic user page and
inspect the generated route graph.

## What Pyganini Gives You

### Build pages from the filesystem

Each package below `app/routes` maps to a URL segment. A route declaration
connects a handler to its adjacent Jinja template. `layout.py` and
`layout.jinja` mark layout ownership for that route subtree.

### Generate checked application interfaces

`pyganini generate` writes the router and typed URL tree below
`app/_pyganini`. `pyganini check` rebuilds the expected bytes in memory and
reports missing, stale, or invalid output without changing files.

### Keep HTMX in the template

Templates use ordinary `hx-get`, `hx-post`, `hx-target`, and `hx-swap`
attributes. Generated URL values remove string paths without hiding the
browser interaction.

### Inspect before you run

The CLI can list routes, show layout chains, explain one request path, find
template route references, and report render units from source. These commands
do not import application modules.

### Own the application boundary

Pyganini generates a Starlette router. Your application decides whether to
serve it through Starlette or mount it in FastAPI. It also owns authentication,
sessions, storage, middleware, static serving, and process management.

## How Pyganini Apps Are Shaped

A larger application can use this route map:

```text
pyproject.toml                 -> dependencies and Pyganini configuration
app/
  main.py                      -> Starlette or FastAPI host
  routes/
    route.py                   -> declares GET /
    handlers.py                -> request handlers for /
    layout.py                  -> layout marker for / and descendants
    layout.jinja               -> layout HTML for / and descendants
    page.jinja                 -> page HTML for GET /
    users/                     -> /users
      route.py                 -> declares GET /users, fragments, and actions
      handlers.py              -> request handlers for /users
      page.jinja               -> page HTML for GET /users
      by_user_id/              -> /users/{user_id}
        route.py               -> declares GET /users/{user_id}
        handlers.py            -> request handlers for /users/{user_id}
        page.jinja             -> page HTML for GET /users/{user_id}
  shared/
    reports/
      page.jinja               -> route-kit HTML; no URL until a route uses it
  _pyganini/
    .pyganini-root             -> generated-root ownership marker
    asgi.py                    -> generated Starlette dispatch and router
    urls.py                    -> generated typed URL helpers
```

Static package names map underscores to URL hyphens. A package named
`by_user_id` creates `{user_id}` in the path. Each `route.py` contains one
static `Route` declaration:

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

Pyganini reads declarations without importing application code. Generation
writes one live route graph for dispatch, URL helpers, checks, and inspection.
Application code imports generated products after generation:

```python
from app._pyganini.asgi import router
from app._pyganini.urls import urls

user_path = urls.users.by_user_id("42").path
```

Pages inherit layouts from their route ancestry. Fragments render without page
layouts. Route kits let several live route owners share typed handlers and
templates while each owner keeps its path and URL surface. Mounted route
subtrees provide filesystem-shaped reuse with explicit selection.

Run source inspection from the application root:

```text
uv run pyganini routes list
uv run pyganini routes layouts
uv run pyganini routes explain /users/42
uv run pyganini routes refs
uv run pyganini routes render-units
```

The generated router can serve on its own or mount below Starlette or FastAPI.
Pyganini runs asynchronous handlers on the event loop and synchronous handlers
in an AnyIO worker thread.

## More Examples

- [Full-feature contact directory](examples/full_feature) combines the public
  route, rendering, navigation, HTMX, asset, SSE, browser, and error surfaces.
- [Chat](examples/chat) connects generated form actions to an application-owned
  SSE room with replay, heartbeats, named HTML events, and subscriber cleanup.
- [Kit route mounts](examples/kit_routes) mounts one reusable reports subtree
  below admin and user owners with different data and selected children.
- [Navigation](examples/navigation) follows HQ and Regional route trees through
  dynamic breadcrumbs, mounted reports, destinations, and semantic Back links.
- [React island](examples/react_island) mounts one application-owned React
  editor inside a server-rendered page.
- [Svelte island](examples/svelte_island) mounts the same bounded interaction
  with Svelte while keeping the server route model unchanged.

## Documentation

- [Getting Started](docs/user/getting-started.md) builds a two-page application
  with a shared layout, a dynamic route, generated URL helpers, route
  inspection, and an application-owned Starlette host.
- [Installation](docs/user/installation.md) covers Python support, package
  installation, runtime dependencies, and host ownership.
- [Project layout](docs/user/project-layout.md) covers the application marker,
  fixed source and generated paths, and file ownership.
- [Command line](docs/user/cli.md) covers generation, non-writing checks, root
  selection, output, diagnostics, and exit codes.
- [Assets](docs/user/assets.md) covers final build projection, fingerprinted
  output, generated lookup, commands, cleanup, host composition, and
  development flow.
- [Bounded client islands](docs/user/client-islands.md) covers explicit
  application-owned roots, lifecycle cleanup, JSON policy, and build ownership.
- [Route inspection](docs/user/route-inspection.md) covers source-only
  declaration, implementation, navigation, mounted-selection, layout, and
  error-render evidence.
- [Routes](docs/user/routes.md) covers live route packages, declarations, path
  mapping, layouts, and static validation.
- [Route middleware](docs/user/middleware.md) covers live route-tree middleware,
  ordering, mounted-owner scope, diagnostics, and host boundaries.
- [Error composition](docs/user/errors.md) covers the optional generated-route
  error callback, response contracts, and host ownership.
- [Route kits](docs/user/route-kits.md) covers shared implementations, typed kit
  values, owner-specific URLs, shared templates, and invocation boundaries.
- [Mounted route subtrees](docs/user/mounted-routes.md) covers reusable
  filesystem-shaped source trees, exact selection, owner-bound URLs, and
  mounted layout order.
- [Navigation](docs/user/navigation.md) covers request-local trails, dynamic
  labels, typed destinations, alternate keys, Back, return safety, and mounted
  ownership.
- [Generated URL interfaces](docs/user/urls.md) covers typed route-shaped paths,
  dynamic values, explicit base paths, and query and request-context
  boundaries.
- [Rendering and responses](docs/user/rendering.md) covers Jinja environments,
  pages, layouts, fragments, render values, and direct Starlette responses.
- [Server-Sent Event helpers](docs/user/sse.md) covers UTF-8 wire framing,
  comments, reconnection headers, Starlette streaming, and application-owned
  operational policy.
- [Browser helpers](docs/user/browser.md) covers the optional fixed-resource
  app, named SSE event swaps, template overlay delivery, explicit mounting,
  and cache revalidation.
- [Template inspection](docs/user/template-inspection.md) covers typed
  development modes, render markers, explicit Jinja call blocks, and the
  optional browser overlay.
- [HTMX and async forms](docs/user/htmx.md) covers visible attributes, generated
  URL values, header helpers, Starlette form parsing, uploads, and validation.
- [CSRF helpers](docs/user/csrf.md) covers the optional signed-cookie helper,
  visible form and HTMX values, validation ordering, and application-owned
  policy.

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

Maintainer architecture records live under [`docs/arch`](docs/arch). The
[release guide](docs/releasing.md) records candidate and trusted-publisher
steps.

## License

Pyganini is licensed under the [Apache License 2.0](LICENSE).
