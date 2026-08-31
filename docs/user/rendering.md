# Rendering and Responses

Pyganini renders route-local Jinja templates when a handler returns `Page` or
`FragmentResponse`. A handler can instead return any concrete Starlette
`Response`; direct responses bypass Jinja and keep their Starlette behavior.

## Environment

The default generated router uses `create_environment()`. It creates a
synchronous Jinja environment with `PackageLoader("app", package_path="")`,
HTML autoescaping for `.jinja`, `.html`, and string templates, and
`StrictUndefined`.

Applications can configure ordinary Jinja features before constructing a
router:

```python
from app._pyganini.asgi import create_router
from pyganini import create_environment

environment = create_environment()
environment.filters["currency"] = format_currency
router = create_router(environment=environment)
```

The supplied environment must have async mode disabled, use
`StrictUndefined` or a subclass, have a loader, and autoescape every generated
endpoint and layout template name. Configure it completely before mounting or
serving the router, then do not mutate it while requests run.

### Shared route-kit templates

A route kit may set one explicit `template_root`, such as
`shared/contact_directory`, and declare the same lowercase `.jinja` filenames
from each live owner. Pyganini resolves the source below `app/` and gives the
existing `PackageLoader("app", package_path="")` the environment name
`shared/contact_directory/page.jinja`. The shared location adds no layout or
request context. The live owner's layout ancestry still wraps a `Page`, and a
kit fragment remains layout-free. See [Route kits](route-kits.md).

### Mounted source templates

A referenced mounted source keeps its templates beside its source route files
below `app/mounts`. The environment name includes that source prefix, for
example `mounts/contact_directory/page.jinja`; the live owner does not provide
a second `template_root`. A mounted page is rendered first, then wrapped by
the live outer layout ancestry followed by the mounted source's inner layout
ancestry. A mounted fragment or action fragment is rendered without layouts.
Mounted source handlers finish their own application I/O before rendering and
own no authentication, authorization, middleware, sessions, persistence,
dependency injection, or dependency scopes.

### Generated error templates

The live root may declare one static `error_page_template` and one static
`error_fragment_template`. A `RouteErrorHandler` returning `Page` uses the
root error page template. Router 404 and 405 outcomes select root layouts;
failures after endpoint selection select that endpoint's live layout chain,
including mounted ancestry. A returned `FragmentResponse` uses the root error
fragment template without layouts. Direct Starlette responses and `None`
delegation do not render. See [Generated-route error composition](errors.md).

## Pages and layouts

A page route declares one adjacent template and returns `Page`:

```python
from pyganini import Page, PageMetadata, PageRouteResponse, route

from .handlers import page

Route = route(page=page, template="page.jinja")
```

`handlers.py` returns the render value:

```python
def page(request) -> PageRouteResponse:
    return Page(
        context={"name": "Ada"},
        metadata=PageMetadata(title="Users", description="User directory"),
        layout={"navigation_label": "People"},
    )
```

The page template receives the `Page.context` keys plus the reserved
`pyganini_inspection` call-block namespace. Each selected `layout.jinja` receives
`child`, `metadata`, `layout`, and that namespace. Pyganini renders
the page first, then wraps it from the deepest selected layout through the root
layout. A `layout.py` marker always requires an adjacent `layout.jinja`; Pyganini
does not import `layout.py` or call a Python layout function.

Only HTML produced by the preceding Pyganini render step is marked safe as
`child`. Application strings in page, metadata, and layout values remain
autoescaped. Applications can pass an explicit MarkupSafe `Markup` value when
they deliberately own that escaping decision.

Jinja rendering, including template load and every layout render, runs in one
AnyIO worker call. Handlers must finish database, network, request-body, and
filesystem I/O before returning a render value. Templates receive no implicit
request, URL helper, dependency container, or I/O facility. Pass a generated URL
surface and any `Navigation` value explicitly in `Page.context`, fragment
context, or layout data when needed. Pyganini never injects request navigation
into Jinja.

## Fragments and actions

Fragments declare an adjacent template and return `FragmentResponse`:

```python
from pyganini import fragment_route, route

from .handlers import fragment_table

Route = route(
    fragments=(fragment_route("/table", fragment_table, template="table.jinja"),),
)
```

The fragment template receives its context plus the reserved
`pyganini_inspection` call-block namespace. It receives no page layouts, metadata,
layout data, request, cache default, or automatic HTMX behavior.

An action can return `Page`, `FragmentResponse`, or a direct Starlette
`Response`, selecting page or fragment rendering respectively. Page handlers
can use the `PageRouteResponse` alias (`Page | Response`), fragment handlers
can use `FragmentRouteResponse` (`FragmentResponse | Response`), and actions
can use `RouteResponse` (`Page | FragmentResponse | Response`). These aliases
are typing-only descriptions of the existing dispatch contract. A declared
template does not prevent a handler from returning a direct Starlette response.

Navigation is explicit application context for these same boundaries. A page,
fragment, or action handler may call `nav(request)` and place
`navigation()` or `navigation_with_trail(...)` in the response context. The
fragment remains layout-free and receives no implicit navigation value. See
[Navigation](navigation.md).

### HTMX response headers and forms

Use `from pyganini import hx` for typed HTMX request-header readers and ordinary
response-header names. Pass response constants through the existing
`Page.headers` or `FragmentResponse.headers` mappings; direct Starlette
responses remain available for lower-level behavior. Pyganini does not choose an
HTMX branch, target, swap, redirect, cache policy, or client response policy.

Direct Starlette form access is asynchronous and uses Starlette's public
`async with request.form(...)` context manager. Finish upload reads before the
context exits. A sync or async mutation action can instead use
`request_data=capture_form(...)`; Pyganini materializes and cleans up an
immutable `Form` before invoking that handler. See
[HTMX and async forms](htmx.md) for explicit limits, validation redisplay, and
upload lifetime.

## Render values and direct responses

`Page`, `PageMetadata`, and `FragmentResponse` are frozen, slotted values.
Construction shallow-copies context, layout, and headers into immutable mapping
views. Context and layout keys must be strings.

Rendered statuses accept body-carrying `2xx` values except 204 and 205, plus
`4xx` and `5xx`. Rendered output is UTF-8 `text/html; charset=utf-8`, with
Starlette calculating `Content-Length`. Render headers cannot set
`Content-Type`, `Content-Length`, `Location`, or `Transfer-Encoding`; use a
direct response for those contracts.

Use Starlette response classes directly for redirects, plain text, JSON,
streaming, files, no-content responses, repeated headers, background work, and
other low-level response behavior:

```python
from starlette.responses import RedirectResponse, Response


def redirect(request):
    return RedirectResponse("/users", status_code=303)


def deleted(request):
    return Response(status_code=204)
```

For a server-sent event stream, applications may use the optional pyganini.sse
wire helper with Starlette's StreamingResponse. Render or serialize each
payload before constructing an event. The helper does not own routes,
iterators, response headers, replay, disconnect handling, or production stream
policy.

HEAD executes the GET handler and completes the same render path. It preserves
the rendered status and headers, including calculated `Content-Length`, while
emitting no response body bytes.

## Failures

Invalid render-value construction raises `TypeError` or `ValueError` locally.
At request time, `PYGANINI014 route-response` reports a result-kind mismatch,
missing declared template, invalid path evidence, or a corrupted render value.
`PYGANINI015 render-configuration` reports an incompatible Jinja environment.
`PYGANINI015 render-template` reports template loading, compilation, undefined
lookup, filter, global, extension, or render failures and preserves the Jinja
exception as its cause. Application handler exceptions still pass through for
the host to present unless the application configured the generated-route
error callback. Missing root error templates and invalid callback results use
localized `PYGANINI019`; error-template and selected-layout failures retain
`PYGANINI015`.
Runtime inspection is off by default and preserves existing response bytes.
See [Template inspection](template-inspection.md) for the typed modes and
explicit component and embedded-fragment boundaries.
