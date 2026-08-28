# Application composition architecture

Live route-tree middleware is the first application-composition slice. Pyganini
selects application-supplied Starlette middleware for generated routes while
the host retains ownership of the server, outer middleware, state, lifespan,
static files, dependencies, authentication, persistence, validation, and
error presentation.

The same boundary applies to final browser assets. Applications mount
`assets/dist` with their host framework and choose cache headers, deployment,
and CDN policy. Pyganini supplies only the offline fingerprint projection and
generated lookup values; it does not provide a `StaticFiles` application,
middleware, response class, or cache policy.

## Graph facts

`_route_graph.py` reads exact `app/routes/**/middleware.py` files through the
held route filesystem owner. It records an immutable marker source, route
prefix, tuple entry count, and each entry source position. It never imports a
middleware module or evaluates its classes and constructor arguments. Each
live `RouteNode` also carries its root-to-owner marker chain. Mounted final
nodes receive the chain of their live owner and never read mounted-source
middleware.

The graph uses the same endpoint path grouping as generated dispatch. Every
method at one normalized path must have the same chain by marker source and
tuple entry positions. `PYGANINI011 route-collision` reports incompatible chains
with path, method, owner, mount, source, and first-difference evidence before
dispatch generation or generated-state mutation.

## Generated projection

`_dispatch_generation.py` emits used marker captures in deterministic
root-to-owner order and passes the flattened captured tuples through
Starlette's public `Route(..., middleware=...)` argument. It keeps one Route per
normalized path, the existing method union, path priority, HEAD handling, and
public `create_router()` and `router` names. Marker-free output gains no
middleware-specific imports, captures, arguments, or products. The independent
generated-route error callback extension is emitted for every graph and still
adds its typed factory parameter and runtime preparation imports.

`_dispatch.py` performs controlled runtime loading after route owner and
callable validation. It imports the recorded module, reads `MIDDLEWARE` through
`vars(module)`, validates the generated tuple count and public Starlette
`Middleware` values, and captures an immutable tuple. Import, binding, tuple,
member, and Starlette construction failures are localized as
`PYGANINI018 route-middleware` with preserved causes. Request-time middleware is
still application-owned and is not transformed by the middleware loader. On
callback-enabled routes, the selected-route error boundary catches exceptions
from the middleware-wrapped application and offers them to the configured
callback; returning `None` preserves the existing exception propagation.

Each `create_router()` constructs fresh Route objects and fresh middleware
instances. Starlette performs the normal request entry and reverse response
unwind. A route middleware short-circuit therefore occurs before Pyganini path
evidence validation, navigation, creators, request-data capture, handlers,
rendering, and background work. Route middleware does not wrap unmatched 404 or
method-mismatched 405 outcomes.

## Host boundaries

The generated Router remains a low-level ASGI application. A selected
Starlette or FastAPI host supplies application state through the original
Request and owns outer middleware, exception handlers, OpenAPI, API routes,
static mounts, and lifespan. A root Pyganini mount follows more specific host
routes. Static files remain before a catch-all root Pyganini mount.

The host or trusted ASGI server supplies one decoded effective `root_path` for
mount and proxy prefixes. Generated request Navigation uses it for canonical
browser hrefs. Application handlers bind URL and asset helpers from the same
scope value. Pyganini reads no proxy header and owns no trusted-proxy policy.

Applications may opt into generated-route error composition by passing a typed
`RouteErrorHandler` to the generated `create_router(error_handler=...)`
factory. The callback receives the original `Request` and `Exception`, gets
first chance for generated 404 and 405 outcomes and matched-route exceptions,
and may return a `Response` or `None`. `None` delegates to the existing direct
or host behavior. It may also return the existing `Page` and
`FragmentResponse` values when the live root declares their static error
templates. Router errors use root page layouts, matched errors use the
selected endpoint layouts, and fragments remain layout-free. The default
`router = create_router()` has no callback and
retains the existing behavior.

The error boundary is outside the matched route middleware chain, so it can
present a route middleware failure. It does not wrap host routes, static files,
outer middleware, lifespan, or deployment, and 404 and 405 still do not enter
route-tree middleware. A handled HTTP exception preserves its status and
headers. A handled non-HTTP exception must send one 500 response before
re-raising the original exception; an exception after response start bypasses
the callback. Callback failures propagate without recursion.

The application still owns the callback implementation, page-versus-fragment
selection, content, HTML, HTMX policy,
logging, authentication, dependencies, localization, and host error handling.
The route middleware convention does not grant authentication or policy
ownership to reusable `app/mounts` sources.

The optional `pyganini.csrf.TokenMiddleware` follows the same host boundary. It
is explicitly mounted by the application with an application-owned
`pyganini.csrf.Guard`; it may also be selected in a route middleware tuple when
that scope is intentional. It issues or reuses a signed cookie token, stores a
private request-scope value, and appends a cookie on response start. It does
not enforce methods, parse bodies, call validation, alter generated products,
or author an error response. The application parses submitted values, calls
`Guard.validate()` before mutation, and chooses the response. The helper rejects
duplicate header or configured-cookie evidence without order selection; the
application must likewise require exactly one textual form token.

The generated `router = create_router()` also leaves template inspection off.
An application may construct a separate
development router with a typed inspection mode, mount `pyganini.browser` at an
application-chosen prefix, and include the inspector script visibly. The host
owns configuration, URL binding through decoded `root_path`, CSP,
authentication, and deployment exposure.
