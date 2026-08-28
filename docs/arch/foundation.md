# Pyganini Foundation Decisions

This document records the foundation rules that later Pyganini implementation
children must preserve. The executable evidence remains isolated under
`probes/foundation/`; none of its names or helper interfaces are public Pyganini
contracts.

## Accepted project-level rules

- Generate one immutable normalized graph, then derive ASGI dispatch and typed
  URL interfaces from that graph.
- Use a public Starlette `Router` as the smallest generated ASGI surface. It can
  run directly or be mounted in an application-owned Starlette or FastAPI host.
- A root mount must follow more specific host routes. FastAPI continues to own
  API routes, OpenAPI, outer middleware, state, and lifespan.
- Construct external paths from the ASGI scope's effective `root_path` and the
  graph-local path. Always append the local path, even when its leading segments
  match the effective root; the effective root already contains proxy and mount
  prefixes and the graph-local path contains neither.
- Classify callables without executing them or reading application wrapper
  descriptors. Classify functions and methods from the outer callable Python
  invokes. Statically accept the demonstrated plain-function `__call__` form
  for callable instances and reject ambiguous descriptors. Await async
  callables directly, offload sync callables through AnyIO, and await an
  awaitable returned by a sync callable only after the sync call has completed
  in the worker thread.
- Reject async generator functions as route callables.
- Async actions may use async request APIs directly. Explicitly opted-in sync
  mutation actions receive immutable `Body` or `Form` values from
  `pyganini.request_data`; capture, upload materialization, and shielded cleanup
  finish on the ASGI side before AnyIO worker offload. The original Starlette
  `Request` remains available for safe synchronous properties. No implicit
  portal, cached-request proxy, second event loop, or total-body policy exists.
- Async form-reading actions use Starlette's public `Request.form()` async
  context manager. Pyganini directly declares the compatible
  `python-multipart>=0.0.32,<0.0.33` dependency; Starlette owns parsing and
  upload cleanup when the context exits. Total-body policy and upload
  materialization remain application-owned or later-child behavior.
- Use Jinja directly with HTML autoescaping, `enable_async=False`, and
  `StrictUndefined` by default. Render the page first, then render the declared
  layout chain from inner to outer in a worker thread. Mark only
  framework-rendered child HTML as safe.
- Extract basic declaration facts with `ast.parse()` without importing route or
  handler modules. Literal data and source-ordered named local or imported
  handler references, including relative imports, form the proven static
  boundary. Track lexical module bindings while excluding function, class, and
  comprehension target scopes. Star imports, keyword expansion, duplicate
  fields, noncanonical `Route` bindings, and unsupported or ambiguous handler
  rebinding fail closed.
- Preserve equivalent Goldr shared route ownership through explicit
  `route_kit`, `kit_fragment_route`, and `kit_action` declarations. A live
  owner creates one typed request-scoped value and selected shared handlers
  receive `(kit, request)` for pages, fragments, and non-captured actions;
  captured actions receive `(kit, request, body)` or `(kit, request, form)`. The
  shared package has no route registration.
- Preserve reusable filesystem-shaped route subtrees through explicit
  creator-free source `route_kit` declarations below `app/mounts` and explicit
  live-owner `route_mount` declarations. The live owner retains URL identity,
  layouts, data, policy, and request-scoped creation; the selected source has
  no independent route identity or application policy.
- Select an application root from explicit input first, otherwise search from
  an explicit start directory toward an explicit filesystem boundary. Resolve
  symlinks before selection, choose the nearest candidate, and never inspect
  call stacks. Explicit selection does not resolve unused search inputs, and
  path-resolution failures use localized root-selection diagnostics.
- Generate one fully annotated `.py` URL interface. Do not generate a paired
  `.pyi`; it duplicates the surface and creates an extra freshness obligation
  without improving the demonstrated checks.
- Provide source-only route inventory through the same immutable graph and
  transient URL-helper projection. Inspection does not import application or
  generated modules, read generated state, persist a manifest, or add a second
  route model.

## Probe evidence

### Dependency and interpreter compatibility

- Question: Do the exact foundation pins resolve and run on the accepted CPython
  release lines without overrides?
- Candidates tested: the exact locked dependency set on CPython 3.14.7 and
  3.13.15.
- Exact versions: uv 0.12.3; CPython 3.14.7 and 3.13.15; Starlette 1.6.0;
  FastAPI 0.141.1; Jinja 3.1.6; AnyIO 4.14.2; python-multipart
  0.0.32; httpx 0.28.1; httpx2 2.12.0; pytest 9.1.1; Ruff 0.16.3;
  mypy 2.3.1; Pyright 1.1.411.
- Exact command: `uv python install 3.13 3.14`; from
  `probes/foundation`, `uv lock --check`, `uv sync --locked --python 3.14`,
  `uv run --locked --python 3.14 pytest`, `uv sync --locked --python 3.13`,
  and `uv run --locked --python 3.13 pytest`.
- Observable result: uv resolved 36 packages without an override; the full
  suite passed 118 tests on both interpreter lines.
- Selected rule or named deferral: retain these exact versions as the probe
  snapshot. Defer production dependency ranges to the project-and-generation
  child.
- Consequence for later child specs: the project-and-generation child can derive
  an overlapping Starlette/FastAPI range from a demonstrated combination, but
  must run its own locked compatibility tests.
- Limitation: exact probe pins prove one combination, not a supported range or
  future release compatibility.

### ASGI surface and host composition

- Question: Should generated routes use a plain Starlette `Router` or a nested
  `Starlette` application, and how must hosts compose it?
- Candidates tested: `Router` and `Starlette`, direct hosting, Starlette
  `/html` mount, FastAPI `/html` and `/` mounts, correct and reversed root-mount
  order, proxy `root_path`, a graph-local path that repeats its mount prefix,
  outer middleware state, host lifespan, and OpenAPI.
- Exact versions: CPython 3.14.7; Starlette 1.6.0; FastAPI 0.141.1;
  httpx 0.28.1; httpx2 2.12.0.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_asgi_composition.py`.
- Observable result: both candidates served the same immutable graph. `Router`
  required no lifespan and worked in every direct and mounted case. A root mount
  placed before `/api/health` returned 404 for that API path; placing the API
  route first preserved it. HTML paths stayed out of FastAPI OpenAPI. Effective
  paths were `/proxy/html/users/12` behind both proxy and prefix, with neither
  prefix duplicated. A graph-local `/html/users/13` route mounted at `/html`
  produced `/html/html/users/13` from its bound `GraphRoute`. Host middleware
  state and startup/shutdown events reached the mounted surface.
- Selected rule or named deferral: select `Router`; require specific host routes
  before a root mount; use effective ASGI `root_path`; leave the top-level
  lifespan to the host.
- Consequence for later child specs: generated-ASGI-dispatch owns conversion of
  the final graph into public Starlette routes. Project-and-generation owns the
  application mounting instructions and route-order diagnostic.
- Limitation: the probe does not settle production route matching, methods,
  redirects, trailing slashes, or generated file ownership.

### Callable invocation and concurrency

- Question: Which callable forms can share one route surface without blocking
  the event loop or mutating host concurrency policy?
- Candidates tested: sync and async functions, bound methods, partials, async
  decorator wrappers, a synchronous decorator wrapper around an async function,
  sync and async callable instances, a callable instance backed by a custom
  `__call__` descriptor, a sync function returning an awaitable, an instance
  with an application-owned `__wrapped__` property, and an async generator
  function; classification before invocation versus result inspection after
  invocation.
- Exact versions: CPython 3.14.7; AnyIO 4.14.2.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_callable_invocation.py`.
- Observable result: all listed forms except the async generator produced their
  expected values. Sync calls ran on a different thread with `contextvars`
  propagated. Original exception types and worker frames survived. Cancellation
  before offload prevented execution; cancellation during offload released the
  waiter while the Python thread continued until application work returned. The
  AnyIO default limiter token count was unchanged. A synchronous wrapper around
  an async function ran in the worker thread before its awaitable result was
  awaited. Callable-instance classification did not access application-owned
  wrapper properties, and a custom `__call__` descriptor failed with a
  deterministic rejection.
- Selected rule or named deferral: classify the outer callable Python invokes
  without executing application code; accept the demonstrated plain-function
  callable-instance descriptor and reject ambiguous descriptor forms; reject
  async generators; invoke async directly; offload sync work with AnyIO; inspect
  and await a sync result only after offload. Cancellation does not promise to
  stop a running thread.
- Consequence for later child specs: generated-ASGI-dispatch owns deterministic
  callable diagnostics and cancellation integration. Public handler specs may
  narrow this demonstrated set but cannot claim an unproven form.
- Limitation: callable-instance descriptor forms beyond a plain function are
  not supported by this evidence. The probe does not define streaming handlers,
  background tasks, thread-pool sizing, or timeout policy.

### Sync-action request data

- Question: How can sync actions consume bodies and forms without another event
  loop or hidden portal?
- Candidates tested: immutable pre-read data, a cached Starlette request passed
  to sync code, restricting direct async request APIs to async callables, and
  parsed-form cleanup after successful and failed upload materialization;
  multiple and duplicate upload references; upload read failures; cleanup
  failures with and without a primary failure; and cancellation during upload
  reading.
- Exact versions: CPython 3.14.7; Starlette 1.6.0; AnyIO 4.14.2;
  python-multipart 0.0.32.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_request_data.py tests/test_callable_invocation.py`.
- Observable result: reading `body()` and `form()` on the ASGI thread produced an
  immutable value for empty, URL-encoded, and multipart input; repeated body
  access used Starlette's cache. Missing multipart boundaries produced a
  localized 400, and injected parser errors retained their type. Every distinct
  parsed upload received one close attempt after successful copying, an injected
  read failure, and cancellation. Cleanup shielding allowed later uploads to
  close. A primary failure kept its type and gained deterministic cleanup notes;
  cleanup-only failures were grouped after every close attempt. Passing a cached
  request would still expose async form APIs to sync code and therefore did not
  provide an honest sync contract.
- Selected rule or named deferral: async actions may use request APIs directly;
  sync actions receive only explicitly pre-read immutable request data for the
  body/form fields a later public contract accepts. Dispatch attempts each
  distinct parsed upload close under cancellation shielding after those values
  have been materialized or materialization fails. A primary failure remains
  primary with cleanup notes; cleanup-only failures use an exception group.
- Consequence for later child specs: the HTMX async-workflow child owns visible
  HTMX behavior, header helpers, and Starlette-owned async form use. The Sync
  Action Request Data successor owns the immutable public request-data shape,
  form limits for sync offload, pre-reading, materialization, and cleanup.
- Limitation: a resource whose own `close()` raises cannot be claimed closed.
  Upload size, spooling, streaming, validation, and application policy remain
  application-owned or require later accepted contracts.

### Jinja rendering and layout composition

- Question: Can direct sync Jinja preserve escaping and visible layout order,
  and which undefined policy should v0 use?
- Candidates tested: configured template inheritance versus explicit
  inner-to-outer layout rendering; default `Undefined` versus
  `StrictUndefined`; event-loop rendering versus worker offload.
- Exact versions: CPython 3.14.7; Jinja 3.1.6; AnyIO 4.14.2.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_jinja_rendering.py`.
- Observable result: both composition mechanisms rendered and escaped page and
  fragment input. Explicit composition preserved declared order, metadata, and
  app-owned layout data while marking only rendered child HTML safe. Application
  markup remained escaped. `StrictUndefined` localized missing required values;
  default `Undefined` silently rendered an empty heading. `|default("fallback")`
  expressed an optional value. Rendering ran off the event-loop thread, and
  exceptions retained their cause.
- Selected rule or named deferral: use direct Jinja with autoescaping,
  `enable_async=False`, `StrictUndefined`, explicit inner-to-outer layout
  composition, and worker offload.
- Production contract: `rendering-responses.md` owns the public environment,
  template context, layout metadata, diagnostics, response construction, and
  safe-child boundary implemented from this evidence.
- Limitation: the probe does not define template filenames, loaders, cache
  policy, error pages, or the application environment customization API.

### Static declaration boundary

- Question: Which basic route facts can syntax prove without importing handler
  modules?
- Candidates tested: literal route data; named local handlers; imported handlers
  with and without aliases; a relative imported handler; handler rebinding and
  forward references; dynamic parameters as data; nested calls; computed values;
  decorator registration; missing symbols; keyword expansion; duplicate fields;
  direct and conditional function, class, import, assignment, annotated,
  augmented, loop, with, exception, match, delete, named-expression, and type
  alias bindings; star imports; duplicate, chained, and destructuring `Route`
  assignments; nested-scope and comprehension targets; a module that raises when
  imported; and identical declarations in different files.
- Exact versions: CPython 3.14.7 and its standard-library `ast` module.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_declarations.py`.
- Observable result: `ast.parse()` extracted stable literal data and preserved
  handler import levels and aliases without executing imports, decorators,
  top-level code, descriptors, or handler bodies. Bindings were resolved in
  source order at the declaration. Identical inputs produced byte-identical
  normalized JSON. Exactly one direct `Route = route(...)` assignment was
  accepted. Other lexical module `Route` bindings, star imports, calls, computed
  values, keyword expansion, duplicate fields, handler rebinding, forward
  references, decorator registration, and missing symbols failed with source
  path, line, column, field, and reason. Function and class bodies and
  comprehension targets did not create false module bindings.
- Selected rule or named deferral: static discovery owns literal route facts,
  named-reference resolution, and lexical module-binding rejection. It does not
  evaluate general Python expressions. Controlled imports own runtime existence,
  expression side effects, and signature checks; mypy, Pyright, and runtime tests
  own their respective compatibility evidence.
- Consequence for later child specs: static-route-graph chooses final filenames
  and syntax within this proven boundary. Generated-ASGI-dispatch defines the
  controlled import/startup phase for callable compatibility.
- Limitation: the fixture syntax is not a public proposal. The probe recognizes
  the direct `TYPE_CHECKING` sentinel without evaluating arbitrary conditions,
  and AST evidence cannot prove runtime annotations, expression outcomes, return
  values, descriptor behavior, or import success.

### Application-root selection

- Question: How should tools find an application root without stack inspection
  or checkout assumptions?
- Candidates tested: explicit input and bounded upward marker search from an app
  root, nested directory, pytest-style start, editor-style unrelated working
  directory, installed-tool directory, empty directory, nested candidates,
  ambiguous markers, symlink, outside-boundary start, missing input paths, and an
  explicit root with invalid unused search inputs. Marker-free fixture
  directories also contained tracked sentinels.
- Exact versions: CPython 3.14.7 and `pathlib` from its standard library.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_root_selection.py`.
- Observable result: explicit input won; otherwise the nearest physical
  candidate inside the supplied boundary won. Symlinks resolved before search.
  Multiple recognized markers at one candidate, an outside-boundary start, and
  no marker produced localized diagnostics. Missing explicit, start, and
  boundary paths identified their input role and preserved the `OSError` cause.
  Explicit selection did not resolve unused search inputs. Process call stacks
  and imports were irrelevant.
- Selected rule or named deferral: explicit root, then bounded nearest-marker
  search; resolve symlinks; fail on same-directory marker ambiguity and no root.
  Defer the final marker and CLI spelling to project-and-generation.
- Consequence for later child specs: every CLI, editor, test, and installed-tool
  entry point must supply or derive an explicit start and boundary; no entry
  point may infer a root from call frames.
- Limitation: the probe marker is disposable and does not choose configuration
  precedence across future project files.

### Generated URL typing

- Question: Can mypy and Pyright honestly check a route-shaped `.py` module or
  paired `.py` and `.pyi` surface derived from the ASGI graph?
- Candidates tested: fully annotated `.py`; runtime `.py` plus `.pyi`; valid
  static and dynamic paths; missing, unknown, and wrong-type parameters; bound
  child access; deterministic generation; and runtime import parity.
- Exact versions: CPython 3.14.7; mypy 2.3.1; Pyright 1.1.411.
- Exact command: from `probes/foundation`,
  `uv run --locked --python 3.14 pytest tests/test_typing_generation.py`,
  `uv run --locked --python 3.14 mypy foundation_probes tests`, and
  `uv run --locked --python 3.14 pyright foundation_probes tests`.
- Observable result: both candidates passed valid usage and both checkers
  rejected missing parameters, unknown parameters, and wrong parameter types at
  the marked source lines. Bound dynamic nodes exposed the child path. Repeated
  generation was byte-identical, and runtime imports returned the checked paths.
- Selected rule or named deferral: select one fully annotated generated `.py`
  module. The generated-URL-interface child owns exact names and shape.
- Consequence for later child specs: the generated URL code remains a
  deterministic, importable product surface checked by mypy, Pyright, and
  runtime tests. The accepted URL-interface child settles naming, quoting,
  explicit base paths, generated location, and packaging.
- Limitation: the probe does not settle naming collisions, URL quoting, query
  parameters, base-path API, mounts, packaging, or generated file locations.

## Later-track assignments

- Project, package, and generation boundaries: production dependency ranges,
  final root marker and CLI spelling, generated paths, lock workflow, and
  non-writing freshness checks.
- Static route graph: public declaration syntax, filenames, normalized graph
  schema, ordering, and static diagnostics.
- Generated ASGI dispatch: graph-to-Starlette route construction, controlled
  handler and kit-creator imports, callable validation, cancellation
  integration, methods, and matching behavior.
- Rendering and response contracts: implemented environment customization,
  local and shared template names, public context values, layouts, and render
  diagnostics.
- Generated URL interfaces and typing: public generated names, collision rules,
  parameters, quoting, mounts, and base paths using the annotated `.py` rule.
- HTMX references and route-local workflows: visible HTMX attributes, header
  helpers, Starlette-owned async forms, and route-local response behavior.
- Sync Action Request Data: immutable sync-action request data, ASGI-thread
  pre-reading, form limits, upload materialization, cancellation, and cleanup.

The foundation probes leave no unassigned technical decision in their scope.
