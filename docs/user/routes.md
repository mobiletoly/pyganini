# Routes

Pyganini reads one live route tree at `app/routes`. It validates source during
`pyganini generate` and `pyganini check`, then emits request dispatch in
`app/_pyganini/asgi.py` and the typed URL interface in `app/_pyganini/urls.py`.

## Route packages

`app/routes` owns `/`. Each live child directory adds one URL segment and must
contain a regular, non-symlink `__init__.py`.

```text
app/
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
      handlers.py
      page.jinja
      by_user_id/
        __init__.py
        route.py
```

Static package names match `^[a-z][a-z0-9_]*$`. Pyganini replaces underscores
with hyphens in browser paths, so `build_info` maps to `/build-info`.

Dynamic packages use `by_<param>`, where the parameter follows the same
lowercase identifier rule. `users/by_user_id` maps to
`/users/{user_id}`. A route position can have one dynamic child. Static
siblings remain valid and take precedence during dispatch. Starlette decodes
matched values and exposes them through `request.path_params` by name.

A descendant cannot reuse an ancestor parameter name. Canonical paths start
with `/` and have no trailing slash except the root path.

Packages matching `^_[a-z][a-z0-9_]*$` and `__pycache__` stay private. Pyganini
does not descend into them. Other child directory forms fail validation,
including uppercase, hyphenated, dotted, spaced, non-ASCII, leading-digit, and
malformed `by_` names.

Pyganini does not follow route-directory, package-marker, `route.py`, or
`layout.py` symlinks. Convention files must be contained regular UTF-8 Python
files. Required endpoint and layout templates must be contained regular UTF-8
files; Pyganini does not parse Jinja source during graph construction.

## Declarations

`route.py` owns one package's endpoint surface through one direct assignment:

```python
from pyganini import action, fragment_route, route

from .handlers import fragment_table, page, post_create

Route = route(
    page=page,
    template="page.jinja",
    fragments=(fragment_route("/table", fragment_table, template="table.jinja"),),
    actions=(action("POST", "/create", post_create, template="form.jinja"),),
)
```

An optional `nav=RouteNav(...)` belongs to this route declaration and applies
to its page, fragments, and actions. A live declaration may also own typed
`destinations=(to(...),)` edges. See [Navigation](navigation.md) for dynamic
labels, destination targets, alternate trails, and explicit template context.

`route()` and `route_kit()` also accept optional static display metadata:

```python
from pyganini import RouteMeta, route

Route = route(
    page=page,
    name="users.index",
    title="Users",
    meta=RouteMeta(
        labels={
            "app.area": "admin",
            "app.permission": "users.view",
        }
    ),
)
```

`name`, `title`, and label strings are opaque application values. They appear
in source inspection only and do not affect matching, URLs, navigation,
rendering, authorization, or generated dispatch. `RouteMeta` copies and sorts
its labels and exposes them as an immutable mapping. Mounted endpoints inherit
metadata from their source `route_kit()` declaration; mount owners do not
override it. Metadata requires at least one endpoint, so it cannot decorate an
error-template-only root declaration. Static source accepts one lexical string
for `name` and `title` and a direct `RouteMeta(labels={...})` call containing
only literal string keys and values. Computed expressions, concatenation,
mapping unpacking, and empty names, titles, or label keys fail declaration
validation. Static route `title` is separate from runtime
`PageMetadata.title`; Pyganini does not copy it into template context.

Import each constructor you use from `pyganini` under its exact name. `Route`
must call `route()` with the keyword fields `page`, `template`, `fragments`,
and `actions`. Fragment and action collections use literal tuples. `page=None`
equals an omitted page, but each declaration needs at least one endpoint.
The typed declaration values are `RouteDef`, `FragmentRouteDef`, and `ActionDef`.
`fragment_route()` returns a `FragmentRouteDef`; `action()` returns an
`ActionDef`; and `route()` returns a `RouteDef`.

The live root `app/routes/route.py` may add the literal fields
`error_page_template` and `error_fragment_template` to `route()`,
`route_kit()`, or `route_mount()`. An ordinary `route()` containing only these
fields is valid and creates no endpoint. The adjacent files are static graph
facts for generated-route error rendering. Descendant live declarations and
every `app/mounts/**` source declaration reject the fields. See
[Generated-route error composition](errors.md).

## Shared route kits

Use [route kits](route-kits.md) when multiple live owners need one page,
fragment, or action implementation with different request-scoped state. The
owner remains in its own route package and declares `Route = route_kit(...)`.
It supplies `create(request)`, selects its own page, fragments, and actions,
and passes a generic `K` to shared page, fragment, and non-captured action
handlers using `(kit, request)`. Captured actions receive `(kit, request,
body)` or `(kit, request, form)`. Omitted surfaces have no endpoint or
generated helper for that owner.

The six public kit names are `KitRouteDef[K]`, `KitFragmentRouteDef[K]`,
`KitActionDef[K]`, `route_kit`, `kit_fragment_route`, and `kit_action`. Python
uses `create=` as the language-idiomatic name for Goldr's `New` field. Exact
kit grammar, strict typing, shared-template roots, and sync/async invocation
are documented in [Route kits](route-kits.md).

Use [mounted route subtrees](mounted-routes.md) when one filesystem-shaped
source tree must be selected and mounted by multiple live owners. Mounted
declarations use the separate public names `KitRouteMount`, `MountRoute`,
`route_mount`, and `mount_route`; the owner keeps the live URL, layout,
request-scoped creator, data, and policy.

For an ordinary `route()` declaration, template values are omitted, literal
`None`, or a direct lowercase ASCII filename matching
`^[a-z][a-z0-9_]*\.jinja$`. They are adjacent to the declaring `route.py`.
Route-kit templates use the same direct filename grammar but resolve below the
owner's explicit `template_root`, as described in [Route kits](route-kits.md).
Creator-free `route_kit()` declarations are valid only in a referenced mounted
source tree and use colocated source templates; a live route-kit owner still
uses the direct route-kit contract.
Calls, constants, concatenation, formatted strings, aliases, keyword
expansion, and other expressions fail static validation. A page template
requires a page handler.

Handlers use one of these source-ordered forms:

```python
def page(request): ...


from .handlers import page
from .handlers import page as user_page
import app.shared.users as shared_users
```

A handler reference can name a local function, a directly imported symbol, or
one attribute on an imported module alias. Bind it before `Route`. Pyganini keeps
the original module, symbol, source binding, and source position without
importing the module. Lambdas, calls, subscripts, chained attributes, forward
local references, star imports, and ambiguous module rebinding fail static
validation.

Decorators do not register routes. A decorated local function remains a valid
named handler because Python binds the function name before `Route`.

An ordinary route handler accepts one positional Starlette `Request` and
returns a supported Pyganini render value or concrete Starlette `Response`. An
action may opt into `request_data=` from `pyganini.request_data`; it then receives
`(request, body)` or `(request, form)` and must be synchronous. A route-kit
creator accepts one `Request`; its selected shared handler accepts
`(kit, request)` for non-captured surfaces, or `(kit, request, body)` or
`(kit, request, form)` for an opted-in action. Plain sync and async functions,
bound Python methods, `functools.partial`, decorated
outer functions, and callable instances with a plain Python `__call__` are
supported. Pyganini invokes async handlers on the ASGI event loop and ordinary
sync handlers in an AnyIO worker thread. Request-data capture completes before
the worker starts. A sync handler cannot call Starlette async request methods;
use an async action for streaming or live form/upload access.

Importing `app._pyganini.asgi` imports each recorded route and handler module,
compares the runtime `Route` surface with generated evidence, validates binding
identity and callable signatures, and captures the handlers. Restart the host
after route source or generated state changes.

## Pages, fragments, and actions

A page owns its package path and reserves `GET` and `HEAD` for collision
checks and dispatch. `HEAD` executes the GET handler with the original HEAD
request, retains its status and headers, and suppresses every response body
payload. It does not remove or recalculate `Content-Length`.

Fragments accept `/` or one local segment matching
`/[a-z][a-z0-9_-]*`. Pyganini normalizes underscores to hyphens. `/` creates an
index fragment at the package path; a page and an index fragment cannot share
one declaration. Fragments reserve `GET` and `HEAD`.

Actions use `POST`, `PUT`, `PATCH`, or `DELETE` and the same local path form.
Different action methods can share a path. An action can also share a path with
a page or fragment because their reserved methods differ.

Examples:

```text
page under users                         -> GET, HEAD /users
fragment_route("/table", ...) under users -> GET, HEAD /users/table
action("POST", "/", ...) under users     -> POST /users
action("PATCH", "/profile", ...) under
  users/by_user_id                       -> PATCH /users/{user_id}/profile
```

Pyganini rejects duplicate normalized fragment paths, duplicate action method and
path pairs, parent local endpoints that collide with child routes, repeated
parameters, and multiple dynamic siblings. Exact endpoint diagnostics name
both owners. URL-helper-only ambiguities such as reserved members, Python
keywords, and static/dynamic helper-name collisions use `PYGANINI016` during the
same generation pass.

One normalized path becomes one Starlette route containing the accepted method
union. A wrong method at a matched path returns 405 with the exact `Allow`
member set. OPTIONS is not implicit. An unmatched path returns 404. Slash
redirects are disabled, so `/users/` does not match `/users` unless both paths
exist independently. Use [Route inspection](route-inspection.md) and its
`routes explain` command to inspect this selection without running a handler.
Explain removes raw query and fragment text, decodes the complete URL path once
as strict UTF-8 to the ASGI path, and displays the resulting dynamic values.
Thus `/users/a%2Fb` becomes `/users/a/b` and cannot match one `{id}` segment,
while `/users/a%252Fb` becomes `/users/a%2Fb` and can capture the literal
`a%2Fb`. The command preserves repeated, trailing, dot, case, and Unicode path
values and does not perform a second capture decode.

Route Explain uses the first generated-dispatch path match before method
selection. A static path can therefore own a POST 405 before a later dynamic
route that accepts POST. It reports `GET`, `HEAD`, every declared action
method, custom unsupported tokens such as `OPTIONS`, the effective
`dispatch_method=GET` for HEAD, and exact 404/405 outcomes. It is source-only:
it does not import application or generated modules, construct a Request or
Router, load Jinja, or execute handlers.

## Layout markers

A valid `layout.py` marks layout ownership for its route package and descendant
pages. It requires adjacent fixed `layout.jinja`. Pyganini records the marker,
route prefix, and template evidence. The static scanner checks `layout.py`
syntax and template UTF-8 but does not inspect bindings, import the module, or
parse Jinja.

For a returned `Page`, Pyganini renders the page template first and wraps it with
selected layouts from deepest to root. Every layout receives exactly `child`,
`metadata`, and `layout`. Fragments receive no layout chain. See
[Rendering and responses](rendering.md) for context, escaping, environment,
worker, status, and header contracts.

## Route-local HTMX workflows

Keep forms, `hx-*` attributes, targets, and swap boundaries visible in the
route-owned Jinja template. Pass generated URL values explicitly in page or
fragment context and let the route declaration own the page, fragment, and
action endpoints. See [HTMX and async forms](htmx.md) for the async Starlette
form and upload boundary.

## Current limits

The graph stays in memory and internal to Pyganini. Generated dispatch accepts the
exact page, fragment, and action render-value matrix plus concrete Starlette
responses; it does not coerce strings, arbitrary mappings, dynamic template
names, or other values. Page handlers can state `PageRouteResponse`, fragment
handlers can state `FragmentRouteResponse`, and actions can state
`RouteResponse`; these are typing aliases over the existing render values and
Starlette `Response`, not runtime wrapper classes. This version does not add
automatic HTMX behavior, apply FastAPI handler semantics, or provide
route-local dependency injection. Use [Route inspection](route-inspection.md)
for the source-only endpoint and effective-layout inventory; it does not import
generated modules or replace the route graph. Its current schemas remain
endpoint-only and do not represent root error-template facts. Route kits are explicit
request-scoped values, not a framework dependency container. Request-data
capture is opt-in on mutation actions only and does not change pages,
fragments, creators, or non-opted-in handlers. See [Generated URL interfaces](urls.md)
and [HTMX and async forms](htmx.md) for the explicit URL and request-data
contracts.
