# Static Route Graph Architecture

`src/pyganini/_route_graph.py` owns filesystem discovery, source normalization,
the immutable graph, derived endpoints, collision checks, and route
diagnostics. `_cli.py` builds one graph after root selection and before it asks
the generation owner to compare or mutate generated state.

`_route_graph.py` depends on `ProjectPaths.routes`, the optional
`ProjectPaths.mounts`, and the pure local path normalizers in
`_declarations.py`. The general generation and filesystem
modules do not depend on the graph. Dispatch and URL generation consume this
graph, and `_inspection.py` consumes it for the source-only route inventory
instead of adding another scanner or route model.

## Filesystem boundary

Discovery starts at the contained `app/routes` package. The scanner lists each
directory in source-name order and processes static children before one dynamic
child. It rejects symlinked live directories, package markers, and convention
files. On POSIX, the scanner holds no-follow directory descriptors from the
selected application root through every live route package and performs entry
checks and convention reads relative to them. On Windows, it holds
non-delete-shared `CreateFileW` directory handles opened with backup semantics
and without reparse-point traversal, rejects reparse points, and opens
convention files through the same non-delete-shared boundary. Both backends
verify each opened convention object is still a regular file. Replacing an
ancestor pathname cannot redirect a read outside the held route tree.

Win32 acquisition captures an originating last-error value before checked
handle cleanup. Reparse, type, attribute, and descriptor-conversion failures
attempt cleanup and expose a cleanup failure without losing the primary cause.
`open_osfhandle` transfers ownership only after it succeeds; the resulting OS
descriptor then owns the handle and receives exactly one close attempt.

Each live route directory needs `__init__.py`. `route.py`, `middleware.py`, and
`layout.py` are the Python graph convention files. Declared endpoint templates
and the fixed `layout.jinja` paired with each marker use the same held,
no-follow filesystem owner and must be regular UTF-8 files. The scanner records
their names and
source positions without parsing Jinja content. Private underscore packages and
`__pycache__` stay outside the live tree; other child directories must match a
static or `by_<param>` form. Other non-directory entries have no graph meaning,
including symlinks whose names do not exactly match a live route-directory
form.

The scanner continues through independent siblings after a localized failure.
Directory-close failures become `PYGANINI009` diagnostics, and cleanup still
attempts every remaining held directory.
Before raising `RouteGraphError`, it sorts reachable diagnostics by diagnostic
family, live owner, mount identity, mounted source path, final path, method,
and source position. Ordinary diagnostics use their application-relative
source path as both owner and source evidence and leave the mount-specific
positions empty. Field and message provide deterministic tie-breakers after
the accepted evidence order.

Referenced mounted sources are scanned below optional `app/mounts` with the
same contained no-follow package, convention-file, template, and UTF-8 rules.
The scanner enters only source identities referenced by a live
`route_mount(...)` declaration; unreferenced mount children do not appear in
the graph inventory. The source scanner caches each referenced identity for the
one graph build and never runs at request time.

The separate `pyganini routes refs` inspection derives its scan roots only from
the graph's retained `TemplateSource` facts. It selects ordinary `app/routes`,
selected mounted source identities, and explicit shared route-kit template
roots, then reuses the same held no-follow directory and regular-file read
primitives for source-only `.jinja` traversal. This traversal does not add
template ownership, reachability, include tracing, or a second graph.

## Static declaration boundary

Pyganini decodes convention files as UTF-8 and parses them with `ast.parse()`.
Graph construction imports no application module and executes no decorator,
top-level statement, descriptor, or handler body.

The route parser tracks lexical module bindings in source order. It excludes
function, class, lambda, and comprehension-local targets. It preserves local
functions, direct imports, aliases, relative import levels, and module-alias
attributes. Unsupported assignments invalidate handler and constructor names.
Star imports and noncanonical module-scope `Route` bindings fail closed.

The parser accepts one direct `Route = route(...)`, `Route = route_kit(...)`,
or `Route = route_mount(...)` assignment in its permitted context. A mounted
source accepts only creator-free `route_kit(...)` and colocated templates;
live owners use `route_mount(create=..., mount=..., routes=...)` with an exact
literal selection allowlist or omitted selection. It normalizes literal page,
fragment, action, mount, and template fields and records each handler's
absolute module, original symbol, source binding, and reference position. Kit
records retain creator evidence and an explicit shared template root only for
live route kits. Template names and selections must be direct literals.
Controlled imports from generated dispatch validate runtime existence, identity,
and callable contracts.

The exact live `middleware.py` convention is parsed without imports or
evaluation. The scanner records the direct non-empty `MIDDLEWARE` tuple
positions and attaches immutable root-to-owner marker chains to final nodes.
Mounted source middleware remains a localized filesystem failure; mounted
final nodes inherit only their live owner's chain. The canonical endpoint path
groups compare effective chains before generation and report `PYGANINI011` when
methods at one normalized path disagree.

## Graph and endpoint view

The graph is a frozen value containing a tuple of frozen route nodes. A node
stores:

- its application-relative source directory and absolute package name
- its canonical graph-local path and ordered parameter names
- an optional normalized route declaration
- an optional layout source, route prefix, and fixed template source
- optional root-only error page and error fragment template sources

Navigation-bearing nodes also retain one normalized `RouteNavSource` and tuple
of live `DestinationSource` facts. Mounted final nodes retain the source
navigation and destination facts separately so generated runtime import
validation can distinguish source defaults from live-owner overrides.

Declarations store one optional page and page template plus sorted fragment and
action tuples with their optional template and request-data evidence. An action
request-data fact is either a bounded body or bounded URL-encoded/multipart
form declaration and keeps its source position. Every collection uses tuples. A
kit declaration has the same surface fields plus creator and template-root
evidence. Mounted nodes also retain live owner evidence, mount
identity, source-route evidence, rebased source path, and composed layout
ancestry. The graph stores application-package-relative template names but no
template content, absolute checkout path, mtime, locale, hash order, or import
state.

Only the canonical live root node may retain the two error template facts.
They are legal on ordinary, kit-backed, and mounted live root owners. A private
`ErrorRenderFacts` projection returns the two templates plus the root layout
tuple. It is derived from the same graph and is not an endpoint, registry,
manifest, or second error graph.

Normalized ordinary and route-kit declarations retain source-positioned
optional name, title, and sorted label evidence. Mounted nodes keep metadata
from the selected source declaration; owner navigation and destination
selection does not override it. The graph also retains owner-specific included
and excluded mounted source candidates from the existing source scan. That
candidate evidence is inspection-only and never enters dispatch or URL plans.

`iter_endpoints()` is the canonical derived view. It joins each node path with
route-local paths and emits endpoint kind, reserved methods, parameters,
handler evidence, source evidence, optional template evidence, optional
request-data evidence, and optional creator evidence. `RouteGraph`
does not cache a second endpoint list.

Node order is depth-first. The root comes first; static siblings sort by
normalized segment and source name; the dynamic sibling follows. Fragments
sort with `/` first and then by path and handler. Actions sort by path, method
rank, and handler. Source positions remain diagnostic evidence but do not make
semantically equal normalized graphs compare unequal after declaration tuple
reordering.

## Collision checks

The scanner reports `PYGANINI011` when a parent has several dynamic children or a
descendant repeats an ancestor parameter. Declaration normalization reports
the same code for duplicate normalized fragment paths and duplicate action
method and path pairs.

The endpoint pass indexes each reserved method and canonical path. Pages and
fragments reserve `GET` and `HEAD`; actions reserve their declared write
method. A repeated key reports both endpoint kinds and both source positions.
This catches a parent fragment or action that claims a child route path. The
expanded mounted graph applies the same exact method-and-path checks to rebased
source endpoints and reports both live owner/source evidence. It also rejects
same-shape dynamic collisions after rebasing; static and dynamic siblings keep
deterministic static-first order.

One static and one dynamic sibling can overlap as match candidates. The graph
keeps static-first order and leaves request matching to generated dispatch.

Navigation graph validation rejects duplicate dynamic keys in one canonical
route ancestry, destination targets absent from the final live graph, and
destination ownership that would cross an excluded mounted selection. Mounted
source declarations cannot own destinations; selected live owners replace the
source destination set with their explicit edges. Destination selector members
are resolved against final canonical route paths, preserving the exact static
or dynamic meaning of each generated member before target validation.

Canonical graph nodes retain predecessor lexical path-string ordering, which
generation and dispatch consume. Source inspection owns a separate private
segment-wise comparator for inventory rows: it sorts shorter prefixes first,
static segments before dynamic segments, and static or dynamic segment text in
ASCII order. Inventory does not create a route winner or a second matcher, and
its comparator must not change canonical graph ordering.

## Command and dispatch boundary

`pyganini generate` and `pyganini check` select and validate project paths, build the
graph, then construct the bootstrap and dispatch plans. A
`RouteGraphError` returns exit code 1 and prints its contained diagnostics.
Graph failure occurs before generated-root inspection or mutation. Check mode
retains its recursive no-write and no-mtime-change guarantee.

`PYGANINI009 route-filesystem` covers route-tree, source-read, package-boundary,
shared-template, and required-template failures. `PYGANINI010
route-declaration` covers syntax, AST normalization, constructor-family, and
template-literal failures.
`PYGANINI011 route-collision` covers tree, local-surface, and exact endpoint
ownership conflicts.

Runtime middleware loading belongs to generated dispatch and reports
`PYGANINI018 route-middleware`; it is not a graph import or a second route model.

`pyganini routes list` builds this graph and then validates the shared URL-helper
projection without constructing a generated artifact or touching
`app/_pyganini`. It reports endpoint rows from `iter_endpoints()`, effective
layout occurrences, static declaration and implementation facts, navigation
edges, root error-render facts, and, when filtered by mount, graph-retained
selection candidates. `pyganini
routes layouts` uses those same occurrences without URL-helper validation and
adds complete page/action chains through the private graph-level
`_selected_layouts` helper. Its final-path tree is an ephemeral presentation
projection, not a second graph or matcher. `PYGANINI017 route-inspection` belongs
to the final in-memory projection and output boundary; graph and `PYGANINI016`
failures retain their existing owners.

`pyganini routes explain` consumes the same canonical `iter_endpoints()` view and
does not alter graph ownership, ordering, mounted selection, or endpoint facts.
After strict one-pass target decoding, it reuses the generated-dispatch path
groups and method projection and calls `PathPriorityRoute.matches()` for path
ownership. It projects the selected canonical endpoint, declaration and
implementation facts, root error-render facts, and shared layout facts
into a transient explanation only; it does not create a second graph or route
matcher, validate URL helpers, or inspect generated state.

`pyganini routes render-units` consumes only template-backed endpoints from the
same `iter_endpoints()` view. It retains `TemplateSource` evidence, reports
selected owner and mount facts, and uses graph-owned `_selected_layouts()` for
page and action layout evidence while leaving fragments layout-free. Its
private immutable projection is an inspection consumer; it does not add a
template graph, layout registry, URL-helper plan, generated-state read, or
runtime render observation. Its final-path comparator is private to inspection
and does not replace canonical graph ordering.
Root error templates remain outside the endpoint-only render-unit schema.
Route list and explain project those graph facts through their richer
inspection contracts.

The graph is not persisted. `_dispatch_generation.py` and
`_url_generation.py` consume `iter_endpoints()` and emit `asgi.py` and `urls.py`
through the existing writer. Static-first node order becomes Starlette route
order, and dispatch preserves the first matching path before method selection
so a later dynamic route cannot override an earlier static path.
Generated-module import then validates runtime `Route` values, template
declarations, and bindings without rescanning the filesystem. Dispatch
generation also derives each page-capable endpoint's root-to-leaf layout tuple
from graph ancestry, including live outer followed by mounted inner layouts;
URL generation derives the live tree and the selection-filtered mounted binding
catalog from the same endpoint view.
Dispatch generation additionally emits the root error render facts once and
method-specific selected layout tuples beside each existing path group.
Controlled import validates the runtime root error fields even when an
errors-only ordinary root produces no endpoint.
Runtime inspection derives immutable marker literals from these existing
endpoint, template, layout, handler, owner, and mount facts during dispatch
generation. The graph gains no inspection registry, browser field, runtime
occurrence, or additional filesystem scan.
