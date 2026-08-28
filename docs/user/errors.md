# Generated-route error composition

Generated dispatch keeps its default Starlette behavior until an application
passes one `RouteErrorHandler` to a fresh generated router. The callback can
return `Page`, `FragmentResponse`, a direct Starlette `Response`, or `None`:

```python
from pyganini import FragmentResponse, Page, PageMetadata, RouteErrorHandler
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app._pyganini.asgi import create_router
from app.routes.handlers import build_layout


def present_error(
    request: Request, error: Exception
) -> Page | FragmentResponse | PlainTextResponse:
    status = error.status_code if isinstance(error, HTTPException) else 500
    if request.headers.get("X-Error-Format") == "text":
        return PlainTextResponse("Request failed", status_code=status)
    if request.headers.get("HX-Request") == "true":
        return FragmentResponse(
            context={"status": status},
            status_code=status,
            headers={"HX-Retarget": "#global-error"},
        )
    return Page(
        context={"status": status},
        metadata=PageMetadata(title="Request failed"),
        layout=build_layout(request),
        status_code=status,
    )


route_error_handler: RouteErrorHandler = present_error
router = create_router(error_handler=route_error_handler)
```

The application root declares the two static templates used for error render
values:

```python
from pyganini import route

Route = route(
    error_page_template="error_page.jinja",
    error_fragment_template="error_fragment.jinja",
)
```

Both fields are optional, literal, and legal only in
`app/routes/route.py`. They are supported by `route()`, `route_kit()`, and
`route_mount()`. An ordinary root `route()` may contain only these fields; it
does not create an endpoint or generated URL. The files are adjacent to the
root declaration and use the same contained, regular, UTF-8 template checks as
endpoint templates. Descendant declarations and `app/mounts/**` source
declarations must not contain them.

## Rendering selection

Pyganini uses the callback result, not request headers, to select rendering:

- a generated 404 or 405 `Page` uses `error_page_template` and the root layout
  chain;
- a `Page` returned for a failure after endpoint selection uses the same root
  error template and that endpoint's selected live layout chain, including
  mounted ancestry;
- every error `FragmentResponse` uses `error_fragment_template` with no
  layouts; and
- direct Starlette responses bypass Jinja, while `None` delegates the original
  outcome unchanged.

Normal route `Page` and `FragmentResponse` rendering is unchanged. The error
templates receive only the explicit render-value context. Page layouts receive
the existing `child`, `metadata`, and `layout` values. Pyganini does not infer
HTMX policy, content, classification, localization, logging, or dependencies.

Returning `Page` without `error_page_template`, or `FragmentResponse` without
`error_fragment_template`, fails before response start with localized
`PYGANINI019 route-error-handler`. Template or layout failures use the existing
`PYGANINI015` rendering diagnostics and preserve their causes.
Any other callback result fails with `PYGANINI019` and reports that the supported
values are `Page`, `FragmentResponse`, a Starlette `Response`, or `None`.

## Preserved HTTP and failure behavior

With a callback configured, Pyganini gives it one first chance for generated 404
and 405 responses, endpoint `HTTPException` values, request-time
`DispatchError` values, and application exceptions before response start. The
callback receives the original Starlette `Request` and exception and is never
invoked twice for the same failure.

A handled HTTP exception must retain its status. Pyganini restores a missing
required header, including the canonical 405 `Allow` value, and rejects a
conflicting value. HEAD keeps status and headers while suppressing body bytes.

For a non-HTTP exception, the rendered or direct response must have status 500.
Pyganini sends it once and then re-raises the original exception after response
completion so host logging and `raise_server_exceptions` behavior remain
intact. Once response start has occurred, Pyganini skips the callback. Callback
failures propagate unchanged and do not recurse.

The callback catches `Exception`, not `BaseException`. Cancellation,
`KeyboardInterrupt`, `SystemExit`, and other control-flow signals are not
translated. Sync callbacks use the existing worker-thread rules; async
callbacks run on the ASGI event loop.

## Ownership boundaries

The callback covers only generated dispatch. Host API routes, static files,
outer host middleware, lifespan, OpenAPI, the ASGI server, and deployment stay
outside it. Matched route middleware runs inside the generated error boundary;
generated 404 and 405 do not enter route middleware.

The generated `router = create_router()` remains callback-free. Each explicit
`create_router(error_handler=...)` call captures its callback independently.
The callback is not stored globally or added to the route graph. Pyganini adds no
error-specific response class, runtime template selection, registry, second
renderer, second graph, host wrapper, or automatic HTMX policy.

When a generated router selects template inspection, successfully rendered
root and matched error pages or fragments receive the same deterministic
boundaries as ordinary render values. Direct callback responses and `None`
delegation remain unmarked. A failed ordinary render sends no partial marker;
a successful fresh error render contains only its own boundaries.
