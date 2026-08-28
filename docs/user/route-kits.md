# Route Kits

Use a route kit when two or more live route owners should render the same page,
fragment, or action implementation while supplying different URLs, titles, or
application policy state. Keep an ordinary import or a small local adapter when
the shared function does not need owner-specific request state; route kits are
not a general dependency-injection system.

## Public declaration

Pyganini exports exactly six direct route-kit names:

- `KitRouteDef[K]`
- `KitFragmentRouteDef[K]`
- `KitActionDef[K]`
- `route_kit`
- `kit_fragment_route`
- `kit_action`

Mounted route subtrees use the separate public names `KitRouteMount`,
`MountRoute`, `route_mount`, and `mount_route`. They are documented in
[Mounted route subtrees](mounted-routes.md), not registered by a route kit.

The Python `create=` field is the idiomatic adaptation of Goldr's `New` field.
Each live owner keeps its declaration in its own `app/routes/**/route.py`:

```python
from starlette.requests import Request

import app.shared.reports as reports
from app._pyganini.urls import urls
from pyganini import kit_fragment_route, route_kit


def create_reports(request: Request) -> reports.ReportsKit:
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    return reports.ReportsKit(table_url=app_urls.admin.reports.table.path)


Route = route_kit(
    create=create_reports,
    template_root="shared/reports",
    page=reports.page,
    template="page.jinja",
    fragments=(kit_fragment_route("/table", reports.table, template="table.jinja"),),
)
```

`create(request)` produces one request-scoped `K`. The selected page, fragment,
or non-captured action receives that value first and the original request
second: `handler(kit, request)`. A captured action instead receives
`(kit, request, body)` or `(kit, request, form)`. The creator and every handler
in one declaration share one generic `K`, so strict mypy and Pyright can reject
a creator for one kit type paired with a handler for another.

An action may opt into `request_data=` from `pyganini.request_data`. Its sync
handler then receives `(kit, request, body)` or `(kit, request, form)` after
the creator has completed and request data has been materialized. The same
bounded parser, immutable upload, cleanup, media-type, and host-policy rules
as ordinary actions apply. Async kit actions remain the direct Starlette form
boundary and do not opt into this payload.

An owner lists only the surfaces it exposes. Omitting a fragment or action
omits its endpoint, dispatch entry, and generated URL helper for that owner.
A shared package contains ordinary Python values and templates. It has no
route identity and does not register anything at runtime.

## Shared templates

`template_root` is one explicit application-relative package directory below
`app`, such as `shared/reports`. Every directory in the root is a regular
non-symlink Python package with a contained regular `__init__.py`. The declared
template filenames remain direct lowercase ASCII `.jinja` literals.

For `template_root="shared/reports"` and `template="page.jinja"`, Pyganini
records:

```text
source: app/shared/reports/page.jinja
environment name: shared/reports/page.jinja
```

The default `PackageLoader("app", package_path="")` resolves that environment
name. The shared file location does not add a layout or policy boundary. The
live route owner's layout ancestry still wraps a returned `Page`, while a
fragment remains layout-free. A live kit with templates must provide
`template_root`; a direct-response-only kit must omit it. A creator-free kit
declaration is a mounted-source declaration and uses colocated source
templates instead.

## Invocation and responses

Kit pages return `Page` or a direct Starlette `Response`, kit fragments return
`FragmentResponse` or a direct response, and kit actions use the existing
`RouteResponse` contract. Creator and handler exceptions pass through
unchanged. Pyganini classifies each callable independently:

- async callables run on the ASGI event loop;
- sync callables run through the host's AnyIO worker limiter with
  `abandon_on_cancel=True`; and
- a sync callable that returns an awaitable is awaited after its worker call
  completes.

Pyganini invokes the creator once and the selected handler once for each request.
It does not cache a kit across methods, requests, endpoints, router instances,
or `HEAD` and `GET`. `HEAD` runs the GET creator and handler with the original
HEAD request, then suppresses response body bytes. A sync creator and sync
handler are not promised the same worker thread; thread-affine resources must
stay inside one application-owned sync handler or use an application-owned
async resource model. An opted-in request-data action runs capture and upload
cleanup on the ASGI side before its sync handler. This does not add storage,
validation, CSRF, or total-body policy.

## URLs and ownership

The live owner owns its URL path and exposed surface. URL generation consumes
the same canonical route endpoints for local and kit routes, so no kit-specific
URL helper type exists. Pass owner-specific generated URL values through `K`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportsKit:
    table_url: str


def table(kit: ReportsKit, request: Request) -> FragmentResponse:
    return FragmentResponse(context={"table_url": kit.table_url})
```

Pyganini adds no Jinja global, request global, navigation registry, or dependency
scope. Navigation values may be passed through the ordinary kit mapping when a
shared handler needs them. Starlette and FastAPI mounting, proxy
`root_path`, host middleware, and application state remain host-owned. Mounted
source selection and rebasing are documented in [Mounted route subtrees](mounted-routes.md);
route kits themselves do not select or rebase mounted sources.

## Inspection

Route-kit endpoints appear in the source-backed `pyganini routes list` inventory
with the same generated URL-helper expressions as ordinary routes. A selected
mounted route-kit source also reports its live owner, mounted source position,
mount identity, and source-relative path. `--mount MOUNT` retains only selected
rows for every live owner of that source identity; excluded declarations and
unselected source rows remain absent.

Inspection reads source evidence without importing route-kit or generated
modules and does not require current `app/_pyganini` state. `pyganini routes layouts`
shows the human layout map, and `pyganini routes explain` reports graph-local path
and method selection for route-kit endpoints. Template-reference analysis
remains a successor inspection command.
