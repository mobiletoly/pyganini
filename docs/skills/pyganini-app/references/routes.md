# Routes, URLs, Middleware, and Errors

Use this reference for route ownership, refactors, layout composition, and
application integration. Begin with `pyganini routes list` and the actual
`app/routes` tree. Generation, checks, dispatch, URLs, and inspection consume one
deterministic source graph; none performs request-time route discovery.

## Route files and static declarations

Every route directory is a regular Python package with `__init__.py`. `route.py`
owns endpoints; `layout.py` marks an adjacent `layout.jinja`; `middleware.py`
owns a live route-tree middleware tuple. Templates and handlers should stay local
to their route. Handler module filenames are application-owned, not conventions.

Static directory names are lowercase Python identifiers; underscores become
browser hyphens. `users/by_user_id` maps to `/users/{user_id}`. Read the decoded
value from `request.path_params["user_id"]`. One dynamic child is allowed at each
position, and ancestor parameter names cannot repeat. Static matches precede
dynamic matches. Leading-underscore private packages stay outside the live tree.
Do not use brackets, hyphens, uppercase names, or symlinks as route conventions.

Import constructors under their exact names and assign `Route` directly:

```python
from pyganini import action, fragment_route, route

from .handlers import create, page, table

Route = route(
    page=page,
    template="page.jinja",
    fragments=(fragment_route("/table", table, template="table.jinja"),),
    actions=(action("POST", "/create", create, template="result.jinja"),),
)
```

Declare handler bindings before `Route`: a local function, directly imported
symbol, or one attribute on an imported module alias. Constructor aliases,
computed declarations, calls used as handlers, dynamic template names, and
keyword expansion do not satisfy the static grammar. Endpoint collections are
literal tuples. Templates are adjacent lowercase `.jinja` filename literals,
except for explicit [kit template roots](shared-kit-routes.md).

Pages and fragments reserve GET/HEAD. Actions accept POST, PUT, PATCH, or DELETE
at `/` or one local segment; they may share a path with GET/HEAD. Collisions and
helper ambiguities fail generation. A page and index fragment cannot share the
same GET path. HEAD executes the GET handler and suppresses response bytes.
Wrong methods return 405; missing paths return 404 unless an explicit additional
page source handles the miss. Trailing-slash redirects are disabled.

Optional static `name`, `title`, and `RouteMeta(labels={...})` are inspection
metadata, not auth policy or implicit template context. Runtime page metadata
belongs in `PageMetadata`.

## Render and URL boundaries

Page handlers return `Page` or a concrete Starlette response, fragment handlers
return `FragmentResponse` or a concrete response, and actions return either
render value or a concrete response. Strings and dictionaries are not responses.
Use `PageRouteResponse`, `FragmentRouteResponse`, or `RouteResponse` typing aliases
when a handler has multiple accepted return types.

Layouts receive `child`, `metadata`, and `layout`; pass app-specific layout
values in `Page.layout`. A page is wrapped from its deepest layout out to the
root. Fragments have no layouts. The synchronous Jinja environment uses
`StrictUndefined` and HTML autoescaping. Configure an ordinary supported
environment before constructing `create_router(environment=...)`; keep async
mode disabled, a loader, strict undefined behavior, and required autoescaping.
Complete all application I/O before rendering.

```python
from app._pyganini.urls import urls

app_urls = urls.with_base_path(request.scope.get("root_path", ""))
home = app_urls.root.path
detail = app_urls.users.by_user_id("42").path
```

Pass URL values into template context explicitly. Dynamic binders accept decoded
one-segment text and quote it; do not pre-encode values. Slash, backslash, empty,
dot/dot-dot, and control values are rejected. Namespace-only nodes have no `.path`.
Bind mount/proxy prefixes from trusted ASGI scope; proxy headers alone do nothing.
Use standard-library URL tools for application query strings.

Generation does not import handlers. Importing generated ASGI modules validates
and captures handlers at startup. Regenerate after source changes and restart
the host so imports reflect current declarations.

## Middleware and errors

A live `middleware.py` binds one direct non-empty tuple:

```python
from starlette.middleware import Middleware

from app.security import RequireUserMiddleware

MIDDLEWARE: tuple[Middleware, ...] = (Middleware(RequireUserMiddleware),)
```

The application implements that middleware. Order follows live ancestors from
root to endpoint, then tuple order. Mounted sources cannot own middleware.
All methods sharing a path need the same effective chain. Host API/static routes,
lifespan, and generated 405 outcomes remain outside route middleware; content
misses can use eligible static live ancestry.

For generated-route error rendering, root `app/routes/route.py` may declare
`error_page_template="error_page.jinja"` and
`error_fragment_template="error_fragment.jinja"`. Supply a sync or async
`RouteErrorHandler` to `create_router(error_handler=...)`. It receives
`(request, error)` and returns `Page`, `FragmentResponse`, a concrete response,
or `None` to delegate. Descendants and mounted sources cannot declare error
templates. Root 404/405 pages use root layouts; selected endpoint failures use
the endpoint chain; error fragments remain layout-free. HTTP status and required
headers must be retained; non-HTTP exceptions require a 500 response and are
re-raised for host logging. Host errors and post-response-start failures stay
outside this callback.

See [Validation](validation.md) for phase-specific evidence and
[Navigation](navigation.md) for explicit request-local trail values.
