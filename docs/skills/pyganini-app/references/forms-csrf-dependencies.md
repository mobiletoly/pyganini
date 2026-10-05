# Forms, CSRF, and Application Dependencies

Read this for request parsing, uploads, mutation policy, and application state.
Pyganini handlers use Starlette `Request`. FastAPI `Depends`, annotations, and
OpenAPI do not define Pyganini routes or inject handler arguments.

## Async parsing and opt-in capture

Direct `await request.body()`, `request.stream()`, `request.form()`, and live
`UploadFile` access belong in async handlers. Finish and close uploads before
returning a render value. Select bounded parser settings and a host-owned total
body policy where needed; parser field/file limits do not impose a global body
limit. Use `async with request.form(...)` for live-form cleanup.

For a sync or async mutation handler needing materialized data, import exact
constructors from `pyganini.request_data`:

```python
from pyganini import action, route
from pyganini.request_data import capture_form

from .handlers import submit

Route = route(
    actions=(
        action(
            "POST",
            "/",
            submit,
            template="result.jinja",
            request_data=capture_form(
                max_fields=8,
                max_files=0,
                max_part_size=4096,
                max_upload_size=4096,
            ),
        ),
    ),
)
```

The handler now takes `(request, form: Form)` and uses `form.values("name")`.
`Form.uploads(field)` exposes immutable uploads with captured byte content;
live Starlette `FormData`/`UploadFile` are not passed into sync workers. Body
capture uses `capture_body(max_bytes=...)` and `(request, body: Body)`.
Captured route-kit actions add the kit as their first argument. Capture is
opt-in for mutation actions, not pages, fragments, or kit creators.

Read the installed public types for exact fields when handling uploads or raw
bodies. Capture performs bounded parsing and cleanup before the handler runs;
it does not add application validation, storage, CSRF, or dependency lifetimes.
Do not call `asyncio.run` inside a sync handler to reach Request APIs.

## Optional signed-cookie CSRF

Applications may choose `pyganini.csrf` or another application policy. When using
the helper, configure a `csrf.Guard` with application-owned stable secret bytes
(at least 32 bytes) and explicitly mount `csrf.TokenMiddleware` at the intended
host or live-route scope. Set `secure=True` for HTTPS and choose the cookie path
for the actual public prefix. Never embed real secrets in examples or source.

The token middleware issues/reuses tokens; it never parses bodies or rejects
unsafe requests. Pass ordinary values into Jinja:

```python
context = {"csrf": csrf, "csrf_token": csrf.token(request)}
```

```jinja
<input type="hidden" name="{{ csrf.FIELD_NAME }}" value="{{ csrf_token }}">
```

For requests needing an inherited header instead:

```jinja
<body hx-headers:inherited='{{ csrf.headers(csrf_token) }}'>
```

Validate before changing state. A form-accepting application requires exactly
one textual token field, then calls `guard.validate(request, token)` and catches
`csrf.ValidationError` at its chosen forbidden-response boundary. The incoming
header takes precedence over a supplied form token; duplicate headers/cookies
are invalid, not first/last-value evidence. Middleware replacement tokens do not
validate the current unsafe request. Keep authentication, authorization, origin
policy, safe-method behavior, and application validation explicit.

## Dependencies and state

Use ordinary application lifespan, request state, typed accessors, or explicit
kit creation. The app owns persistence and resource cleanup. No framework DI
container or hidden dependency registry is needed. Use
[HTMX fragments and actions](htmx-fragments-actions.md) for visible form/swap
markup and [Shared kit routes](shared-kit-routes.md) for shared request values.
