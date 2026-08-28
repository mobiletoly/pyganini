# Project Layout

A Pyganini application has this fixed package boundary:

```text
<app-root>/
  pyproject.toml
  app/
    __init__.py
    shared/
      __init__.py
      reports/
        __init__.py
        page.jinja
    mounts/
      __init__.py
      contact_directory/
        __init__.py
        route.py
        layout.py
        layout.jinja
        page.jinja
    routes/
      __init__.py
      route.py
      middleware.py
      layout.py
      layout.jinja
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
    src/                       optional application-owned source
    build/                     final browser-ready input
    dist/                      fingerprinted managed output
    .pyganini/assets.json         managed cleanup state
    pyganini_assets_gen.py        generated typed lookup
```

The application root contains an empty table with this exact spelling:

```toml
[tool.pyganini]
```

This table is the only Pyganini project marker and currently accepts no keys.
Malformed TOML, a non-table value, or an unknown key is an error. Pyganini does not
read YAML, environment variables, imported modules, source-checkout paths, or
call frames to select a project.

The application owns `pyproject.toml`, `app/__init__.py`, and all ordinary
application code under `app/shared/`, `app/mounts/`, and `app/routes/`. Each live route
directory is a regular Python package with an
`__init__.py`. `route.py` declares endpoints, `middleware.py` declares live
route middleware, and `layout.py` marks layout ownership. A middleware marker
requires one direct non-empty `MIDDLEWARE` tuple of Starlette `Middleware`
values. A layout marker requires adjacent `layout.jinja`. A page, fragment, or
action can declare one adjacent route-local `.jinja` template in `route.py`.
An ordinary or route-kit declaration may also retain optional static
`name`, `title`, and `RouteMeta(labels=...)` display evidence in the graph.
The live root `app/routes/route.py` may additionally declare adjacent error
templates through the exact `error_page_template` and
`error_fragment_template` fields. Descendant live routes and mounted source
declarations cannot own those fields.
Other files in the package have no route-graph meaning. Private
child packages named with a leading underscore and `__pycache__` stay outside
the live route tree.

An `app/shared/` package is application-owned ordinary code and templates. A
route-kit owner may name one explicit shared template package with
`template_root="shared/reports"`; Pyganini validates that package and its declared
templates but does not scan it for routes, layouts, registrations, or other
conventions. Shared template location does not change the live owner's layout
ancestry.

`app/mounts/` is an optional regular Python package containing reusable
filesystem-shaped route sources. A referenced source tree has the same
contained package, route, layout, and template rules as the live route tree,
but its `route_kit()` declarations are creator-free and have no live URL
identity until a route owner mounts them. Unreferenced children are ignored.
Mounted sources do not contain generated files or application policy.
Their `route_kit()` metadata belongs to the source declaration and is shared by
every owner that selects that source route.

Pyganini owns every non-transient entry under `app/_pyganini/` after creating the
exact `.pyganini-root` ownership marker. Application code must not edit or add
files inside the generated directory. When `assets/build` exists, Pyganini also
owns the fingerprinted files below `assets/dist`, `assets/.pyganini/assets.json`,
and `assets/pyganini_assets_gen.py`. The application owns `assets/__init__.py`,
`assets/build`, optional `assets/src`, static serving, cache policy, and
deployment. See [Assets](assets.md).

Generated artifact names are portable POSIX-relative paths. Pyganini rejects
backslashes, drive forms, platform-reserved components, and exact or
case-normalized file and ancestor collisions. An expected file that is a
directory, symlink, reparse point, FIFO, socket, or device is an ownership
conflict and is not read as generated content.

Generated files are inspectable product surface. Keep `app/_pyganini/` visible to
Git. Python bytecode, `__pycache__` directories, and `*.pyc` or `*.pyo` files
are transient and do not participate in generated-state comparisons.

The generated package contains a route-neutral `__init__.py`, deterministic
`asgi.py`, and deterministic `urls.py`. `app/routes` owns the root route
position, and its package marker does not declare an endpoint. Pyganini builds the
static graph in memory before generated-state work and does not persist a
separate graph or manifest.

Application host code imports the router explicitly:

```python
from app._pyganini.asgi import router
```

The generated module also exposes
`create_router(environment=..., error_handler=..., template_inspection=...)`
for an
application-configured synchronous Jinja environment and optional
application-owned `RouteErrorHandler`. Both names are typed; each factory call
returns a new public Starlette `Router`. The default `router` is callback-free;
it also uses `TemplateInspectionMode.OFF`.
see [Error composition](errors.md) for the opt-in behavior.

Application code imports generated URL helpers directly:

```python
from app._pyganini.urls import mount_urls, urls
```

`urls` is the live route tree. `mount_urls` is the typed catalog used to bind
selection-filtered mounted source helpers to a specific live owner. The
generated package does not re-export either value from `app._pyganini`, and Pyganini
does not re-export application URLs from `pyganini`.

`router` is a public Starlette `Router`. It can serve directly or mount under
an application-owned Starlette or FastAPI host. Keep more specific host routes
before a root mount. The host owns lifespan, middleware, exception handling,
state, ASGI server, and deployment.

Live route middleware is application code selected by the route tree. It runs
only after a generated path and method match, uses the original Starlette
`Request`, and does not wrap static files, generated 404 or 405 responses, or
outer host failures. See [route middleware](middleware.md) for its ordering,
diagnostics, and ownership boundaries. Generated-route error composition is
optional application code; host routes, static files, and outer failures stay
outside it.

See the [full-feature example](../../examples/full_feature) for a complete
downstream project with this layout, committed generated output, and an
application-owned host.
The installed `pyganini.browser` package contains the two fixed helper resources.
They are not application assets or generated products. Applications mount the
fixed-resource app and expose either URL explicitly.
