# Rendering and Response Architecture

`src/pyganini/_render.py` owns Pyganini's public render values, strict synchronous
Jinja environment, render-value validation, layout composition, AnyIO offload,
deterministic inspection marker encoding, the private template call-block
namespace, and conversion to a Starlette HTML response. It does not own route
discovery, handler invocation, host policy, error pages, URL generation, HTMX
behavior, or application I/O. Generated error composition reuses this renderer
but leaves error content and selection policy application-owned.

## Static and generated facts

The route declaration owns one optional literal route-local template for each
page, fragment, or action. A kit declaration may instead resolve those direct
filenames below one explicit `template_root`, such as
`shared/contact_directory`. Template filenames match
`^[a-z][a-z0-9_]*\.jinja$`. A `layout.py` marker pairs with fixed adjacent
`layout.jinja`.

The live root may also retain one literal error page template and one literal
error fragment template. They use adjacent root files and the same held
filesystem validation. The graph keeps those facts once on the canonical root
node with its root layout tuple; endpoint nodes do not receive copies.

The held route-tree filesystem backend validates required local and shared
templates as contained regular UTF-8 files without parsing Jinja. Endpoint
template evidence and layout marker, prefix, and template evidence live in the
immutable `RouteGraph`. Template names and source positions affect graph and
generated identity; template content does not. A shared template records its
complete `app/...` file source, package-relative environment name, explicit
`template_root`, and separate route-declaration position. Its file location
does not add layout ancestry. Request-time render diagnostics retain and print
the route-declaration position with the template root, source, and environment
name.

A referenced mounted source resolves colocated templates below `app/mounts`
with an environment name such as `mounts/contact_directory/page.jinja`; it has
no `template_root`. Its page is rendered first, then the live outer layout
ancestry and mounted inner layout ancestry are applied in that order. Mounted
fragments remain layout-free. Source handlers finish application I/O before
rendering, and mounted sources own no authentication, authorization,
middleware, sessions, persistence, dependency injection, or dependency scopes.

`pyganini routes render-units` reports this retained declaration evidence without
loading Jinja or executing a handler. A declared template identifies a static
render capability and its selected layout facts; it does not prove that a
request will return `Page` or `FragmentResponse`. Actions therefore expose a
conditional page-result layout chain in inspection, while direct Starlette
`Response` results remain outside template and layout observation.
The current render-units schema remains endpoint-only and intentionally omits
root error-template facts.

Generated dispatch may pass immutable marker, effective layout-marker, and
eligible embedded-fragment facts beside existing render evidence. The renderer
adds `pyganini_inspection` only to each render mapping and never mutates the Jinja
environment. Template loading and rendering still occur once per selected
template in the same worker call. `OFF` preserves response bytes.

`_dispatch_generation.py` emits those facts into `app/_pyganini/asgi.py`. It
selects page layout chains from graph ancestry in root-to-leaf order. Controlled
route imports and handler capture still happen once at generated-module import.
The module then exposes exactly these public names:

```python
def create_router(
    *,
    environment: Environment | None = None,
    error_handler: RouteErrorHandler | None = None,
    template_inspection: TemplateInspectionMode = TemplateInspectionMode.OFF,
) -> Router: ...


router: Router = create_router()
```

Each factory call validates or creates an environment, validates the optional
application-owned error callback, and builds a new ordered Starlette router
while reusing captured handlers and immutable generated facts. No environment
singleton, runtime template registry, graph, manifest, host app, or middleware
is generated.

## Environment invariant

The default uses `PackageLoader("app", package_path="")`, Jinja
`select_autoescape` for `.jinja`, `.html`, and string templates,
`StrictUndefined`, and `enable_async=False`. A supplied environment must remain
synchronous, use `StrictUndefined` or a subclass, have a loader, and resolve
autoescape true for every emitted endpoint and layout name. Validation does not
clone, mutate, cache, or take ownership of the environment.

## Render and safety invariant

A page render loads the endpoint template with `Page.context` plus the reserved
`pyganini_inspection` namespace, then walks the selected root-to-leaf layout tuple
in reverse. Each layout receives the preceding rendered HTML as `Markup` under
`child`, the unchanged `PageMetadata`, the shallow-copied page layout mapping,
and a namespace carrying the same endpoint's eligible embedded fragments. The
root layout renders last and is outermost. No other application value is marked
safe.

A fragment renders only its endpoint template with its shallow-copied context
and the reserved namespace. An action selects page or fragment rendering from
its returned Pyganini value. Direct Starlette responses bypass all render work.
Page and fragment endpoint kind mismatches fail closed.

The same renderer handles callback render values. Router-level error pages use
the root error page template and root layouts. Matched error pages use that
template and the selected endpoint's method-specific layouts. Error fragments
use the root fragment template with no layouts. Status and required-header
validation occurs after rendering, and HEAD suppression remains at the
existing send boundary.

Runtime fail-closed normalization, immutable mapping snapshots, the complete
template load, page render, and layout chain run through one
`anyio.to_thread.run_sync(..., abandon_on_cancel=True)` call with the host's
default limiter. Pyganini creates no event loop and does not mutate limiter state.
The ASGI thread constructs `HTMLResponse` after the worker returns Unicode,
validated status, and validated headers.

## Response and diagnostic invariant

Render-value constructors shallow-copy and freeze mappings, validate string
keys, statuses, and Latin-1 header values, reject case-ambiguous headers, and
reserve HTML content and framing headers. Rendered bodies use Starlette's UTF-8
HTML response implementation. The existing HEAD wrapper suppresses body
messages after the GET handler and full render path complete, preserving status,
headers, streaming framing, and background behavior.

`PYGANINI014 route-response` owns result selection and render-value contract
failures. Its diagnostics name the surface-specific accepted results, handler
evidence, declared template evidence, and selected layout chain. `PYGANINI015
render-configuration` owns generated-router environment failures. `PYGANINI015
render-template` identifies endpoint template evidence including the template
root, complete template file source, and environment name; for layouts, it
identifies marker source, route prefix, template source, and chain position.
Underlying Jinja or loader exceptions remain the cause. Handler exceptions and
direct response behavior remain unchanged when no error callback is configured.
Missing callback templates and invalid callback results use `PYGANINI019`;
error-template and selected-layout failures use `PYGANINI015` and preserve their
causes without invoking the callback again.
See `docs/user/errors.md` for the opt-in generated-route error boundary and its
response contracts.

## Ownership boundaries

Jinja is the only built-in renderer and there is no renderer abstraction.
Starlette owns direct redirects, text, JSON, streaming, files, bodyless
responses, encoding, content length, and ASGI messages. The application owns
environment extensions, cache policy, HTMX client policy, middleware, state,
lifespan, generated-route error presentation, exception policy, server, and
deployment. The public `pyganini.hx`
constants feed the existing response-header mapping; they do not add a
response owner. URL, form, inspection, mounted-source, navigation, and
error-page work must reuse these facts and owners rather than creating a
parallel rendering model.

The optional pyganini.sse module is a separate wire-format helper. It returns
complete UTF-8 event and comment frames and reads Last-Event-ID through
Starlette's public request headers. It does not render Jinja or create a
streaming response; applications compose it with Starlette StreamingResponse
after rendering or serializing payloads.

The public handler aliases `PageRouteResponse`, `FragmentRouteResponse`, and
`RouteResponse` describe the existing contracts as `Page | Response`,
`FragmentResponse | Response`, and `Page | FragmentResponse | Response`.
They are typing-only aliases. Starlette remains the owner of concrete direct
responses, and no duplicate Pyganini response classes are introduced.
