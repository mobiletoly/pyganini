# Route middleware

Pyganini can compose application-owned Starlette middleware for live route paths.
Place one exact convention file in a live route package:

```text
app/routes/.../middleware.py
```

It must contain one direct, non-empty tuple binding:

```python
from starlette.middleware import Middleware

from app.security import RequireUserMiddleware

MIDDLEWARE: tuple[Middleware, ...] = (Middleware(RequireUserMiddleware),)
```

The value must be a tuple literal. Conditional assignment, star expansion,
augmented assignment, deletion, duplicate binding, later rebinding, and an
empty tuple fail static validation with `PYGANINI010 route-declaration`. Static
validation parses the file without importing application code. An unused marker
is still validated, but generated dispatch imports only markers used by a final
endpoint.

Middleware order follows the live route tree from `app/routes` root to the
endpoint owner, then the tuple order within each marker. Requests enter the
outermost value first and responses unwind in reverse order. Pages, fragments,
actions, route kits, and mounted endpoints use the same rule. A mounted
endpoint inherits middleware only from its live `route_mount(...)` owner;
`app/mounts/**/middleware.py` remains rejected with `PYGANINI009`, and excluded
mounted declarations contribute nothing.

One normalized path remains one Starlette `Route`. Every method in that path
must have the same effective middleware chain. A difference fails closed with
`PYGANINI011 route-collision`; Pyganini does not merge chains or create a second
same-path matcher.

Generated dispatch imports the selected marker modules during its existing
controlled startup phase. It reads the direct `MIDDLEWARE` value from the
module dictionary, validates the tuple and every `starlette.middleware.Middleware`
member, and preserves import and validation causes as
`PYGANINI018 route-middleware`. Each `create_router()` call builds fresh Starlette
route middleware instances. Marker-free generated output gains no
middleware-specific imports, captures, or route middleware projection; the
independent generated-route error callback extension remains present.

Route middleware runs only after Starlette accepts a generated path and method.
It can short-circuit with an application response before navigation, a kit
creator, request-data capture, a handler, rendering, or background work runs.
It does not wrap generated 404 or 405 responses, static mounts, host API
routes, lifespan, or outer-host failures. Exceptions pass to the enclosing
host unchanged unless the application opts into generated-route error
composition with `create_router(error_handler=...)`. The callback boundary sits
outside matched route middleware, so it can present a route middleware
exception; 404 and 405 still bypass route middleware.

The host application owns authentication, authorization, sessions, persistence,
validation, dependencies, total-body policy, static files, outer middleware,
lifespan, exception presentation, server, and deployment. Handlers retain the
original Starlette `Request`; direct handlers may use application-owned typed
accessors, and route-kit owners use `create(request)`. FastAPI `Depends` is not
a Pyganini handler contract.

The optional `pyganini.csrf.TokenMiddleware` is also application-owned. Mount it
explicitly at the host when all HTTP surfaces need a token, or in a selected
route middleware tuple when the narrower coverage is intentional. It issues or
reuses a token but never rejects requests or parses request bodies. The
application supplies the `csrf.Guard`, chooses ordering, parses submitted
values, calls `guard.validate()` before mutation, and chooses the failed
response. Duplicate configured cookies are invalid middleware evidence and are
replaced without rejecting the request; duplicate token headers fail validation,
and form-accepting applications must require exactly one textual token value.

## Host composition and resources

The host owns the public URL prefix. When an application is mounted below a
proxy or another host route, `root_path` remains in the ASGI scope and generated
URL helpers carry the mounted prefix; route middleware must not hard-code a
public prefix. Put host static mounts before the Pyganini mount when their paths
could overlap. Static files are host-owned and do not enter route middleware.

Applications also own resource lifetime and cleanup for authentication,
sessions, database work, streams, and other request resources. Route middleware
must preserve the ASGI `receive` and `send` contract, cancellation, and
application-owned cleanup. Pyganini does not add a total-body policy or silently
close resources owned by the host or application.

## ASGI and error boundaries

The reference model is a small pure-ASGI wrapper around
`await app(scope, receive, send)`. It can wrap `receive` or `send` when the
application needs streaming or protocol-level behavior. Starlette's
`BaseHTTPMiddleware` is application-owned and convenient for simple request
state, but its documented context-variable and request-streaming limitations
do not define Pyganini's middleware contract. Use a pure-ASGI middleware when
those boundaries matter.

With a direct generated `Router`, low-level Starlette behavior remains visible
when no callback is configured. A Starlette or FastAPI host may add exception
handlers, outer middleware, static mounts, API routes, and `root_path`
composition. See [Error composition](errors.md) for the optional callback and
its unchanged host boundary.
