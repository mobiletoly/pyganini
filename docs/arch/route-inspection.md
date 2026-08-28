# Route Inspection Architecture

`src/pyganini/_inspection.py` owns the source-only route inventory and render-unit
projections. It does not scan the filesystem, import application or generated
modules, create a route registry, persist a manifest, or add a runtime hook.
`_cli.py` owns the nested argparse commands and diagnostic/output boundary.

`src/pyganini/_template_references.py` owns the separate direct HTMX reference
projection. It receives the already-selected `ProjectPaths`, canonical
`RouteGraph`, and existing `_URLHelperPlan`; it does not select a root, create
template ownership, or expose a public Python model.

## Data flow

The command has one read-only flow:

```text
ProjectPaths
    -> build_route_graph(paths)
    -> _url_helper_projection(graph)
    -> immutable declaration and implementation evidence
    -> live RouteInventoryRow tuple
    -> optional owner-specific mounted candidate projection
    -> graph-owned root error-render evidence
    -> complete text or JSON bytes
    -> stdout
```

`pyganini routes layouts` shares the first two stages, then follows this branch:

```text
RouteGraph
    -> inventory occurrences without URL-helper validation
    -> graph-level endpoint layout selection
    -> ephemeral final-path display tree
    -> complete ASCII bytes
    -> stdout
```

`pyganini routes explain` shares project selection and graph construction, then
follows a dispatch-equivalent branch:

```text
RouteGraph
    -> shared _PathGroup and method-endpoint projection
    -> one strict decoded ASGI path and method scope
    -> PathPriorityRoute.matches() in emitted group order
    -> selected Endpoint, shared declaration evidence, and graph-selected layouts
    -> graph-owned error-render evidence
    -> complete ASCII explanation or one PYGANINI017 diagnostic
```

`pyganini routes render-units` follows a separate graph-only branch:

```text
RouteGraph
    -> iter_endpoints() with retained TemplateSource facts
    -> graph-owned _selected_layouts() for page and action endpoints
    -> immutable ordered render-unit rows
    -> complete text or pyganini.render_units.v1 bytes
    -> stdout
```

`pyganini routes refs` follows the same graph-first boundary:

```text
RouteGraph and URL-helper projection
    -> graph-derived template roots
    -> held no-follow `.jinja` source files
    -> Jinja `Environment.lex()` masking
    -> standard-library `HTMLParser` start-tag callbacks
    -> isolated `Environment.parse()` expressions
    -> exact path/helper-shape resolution
    -> immutable ordered rows
    -> complete text or `pyganini.refs.v1` bytes
```

The target parser is private to `_inspection.py`. It extracts only the path,
ignores raw query and fragment text, validates percent escapes, and decodes the
complete path once as strict UTF-8. The resulting value is passed as
`scope["path"]`; captures are not decoded again. The branch does not construct
a `Router` or `Request`, call ASGI, import application or generated modules,
load Jinja, or inspect generated state.

It never calls bootstrap planning, dispatch artifact planning, generated-state
comparison, or generation. Graph construction is the accepted AST and held
filesystem evidence boundary. URL-helper construction is the same transient
tree, mounted catalog, member spelling, and `PYGANINI016` validation used by
`url_plan`; its final-path expression facts are discarded after rendering.

The render-unit branch does not build the URL-helper projection and does not
read graph-selected Jinja files. It consumes only retained template facts and
layout facts already required by graph construction.

The row and supporting evidence models are private, frozen, and slotted. They
contain normalized route values, source-positioned display metadata,
navigation and destination edges, mounted selection, handler and template
bindings, root error-render facts, and helper expressions. They store no
checkout path, content, mtime, hash, imported object, request value,
generated-state fact, or mutable collection.

Render-unit rows are a separate private, frozen, slotted projection. Each row
contains one template-backed page, fragment, or action endpoint, its retained
`TemplateSource`, source and owner positions, selected mount evidence, layout
mode, and a tuple of retained marker/template layout evidence. Layouts are not
independent render-unit rows. The projection does not add parameters, helper
expressions, handler symbols, template content, or runtime response facts.

## Row derivation

`iter_endpoints(graph)` is the sole live endpoint view. Each endpoint produces one
page, fragment, or action row with its exact method tuple, final path,
parameters, source, owner, mount, and selected source path. Several methods or
surface kinds may share a final path; they remain separate rows and use the
same deduplicated live helper expression. Each endpoint row receives one
shared declaration projection derived from its normalized source and the final
live graph. It includes metadata, effective navigation, outbound and inbound
destination edges, accepted trail keys, mount ownership, and Python
implementation evidence.

Normal inspection remains live-only. Mount-filtered inspection additionally
projects the graph's retained source candidates. Included rows reconcile with
live rows and receive `selection=included`; excluded candidates receive a
non-live `kind=route` row with no methods, helper, or implementation. Candidate
projection never changes `iter_endpoints()`, URL helpers, layouts, references,
render units, dispatch, or matching.

Ordinary layout rows come from `RouteNode.layout` on non-mounted graph nodes,
including a live owner placeholder with no endpoint declaration. Their final
path is the layout route prefix and their source is also their owner.

Mounted layout rows come only from the `layouts` tuples already attached to
selected mounted nodes. A mounted source layout is recognized from its graph
source position, rebased by joining the live owner path with its
source-relative layout prefix, and recorded with the source layout position,
live owner position, mount identity, and source-relative prefix. The row is
deduplicated by owner position, mount identity, layout source position, and
rebased final prefix. Live outer layouts remain ordinary rows.

The row sorter uses inspection's private segment-wise path comparator: root
first, shorter prefixes first, static segments before dynamic segments, ASCII
static text order, and ASCII dynamic parameter order. It does not reuse or
alter canonical graph ordering, which remains the predecessor lexical order
consumed by generation and dispatch. Kind, method, owner, source, mount, source
path, and helper are deterministic tie-breakers. Filtering preserves this
inspection order.

## Output and failure boundary

The text renderer computes widths from the fixed ASCII header and retained row
values. It pads every column except the last with two-space separators and
does not emit trailing padding. The JSON renderer inserts keys in the enriched
in-place `pyganini.routes.v1` order, including global error-render and structured
declaration values, and encodes the complete object before the first write.
Both renderers consume the same frozen rows.

Root, configuration, project-layout, graph, and URL-helper failures retain
their existing owners and exit behavior. A projection or encoding failure is
`PYGANINI017 route-inspection` at the command boundary. No failure path prints a
partial inventory or Python traceback. A failing stdout owner is handled after
the complete UTF-8 payload has been prepared.

## Direct template references

The reference scanner derives roots from graph-retained `TemplateSource` facts:
ordinary `app/routes`, each selected mounted source identity below
`app/mounts`, and each explicit shared route-kit `template_root`. It collapses
nested roots, holds each directory without following symlinks or reparse
points, reads exact-suffix `.jinja` regular files as strict UTF-8, and scans
unreferenced files below a selected root. A file outside the selected roots is
not reachable to this inspection surface.

Jinja control, line-statement, comment, and raw delimiters are masked through
the public lexical token stream while output data remains data. Variable blocks
become deterministic file-local sentinels; only one isolated variable
expression is parsed through the public Jinja AST interface. Python's
standard-library `HTMLParser` supplies start-tag and attribute callbacks. It
does not maintain a DOM, element stack, inherited HTMX state, or HTML repair
model. The callback line is retained and the reported column is always `1`.

Resolution uses exact method-plus-path indexes for literals and normalized
canonical helper shapes for direct `urls...path` expressions. A literal query or
fragment suffix is removed only for lookup. Dynamic values and unsupported
expressions remain inventory rows. Text and JSON consume one sorted immutable
row tuple; the JSON object uses the versioned `pyganini.refs.v1` contract. The
command does not render, import, execute, trace, write, or participate in
`pyganini check`.

## Render-unit projection

`iter_endpoints(graph)` is the only endpoint view for render-unit rows. An
endpoint is retained only when `Endpoint.template` is not `None`. Page rows
use `layout_mode=page` and call `_selected_layouts()` once for their complete
outer-to-inner chain. Fragment rows use `layout_mode=none` and an empty chain
without consulting layout selection. Action rows use `layout_mode=page-result`
and retain the same chain as page rows; only an action returning `Page` uses it
at runtime.

The private comparator applies the inspection path order, then kind, method,
owner, source, mount, selected source path, template name, and remaining
serialized evidence. It does not alter canonical `RouteGraph` order. Text and
`pyganini.render_units.v1` JSON are encoded from the same immutable tuple, with
all nested source positions and layout evidence emitted in locked key order.
Projection, reconciliation, ordering, encoding, and stdout failures use the
`pyganini routes render-units: PYGANINI017 route-inspection` boundary.

## Ownership and successor boundaries

The command is a read-only source inspection surface. It does not read
`app/_pyganini`, compare generated bytes, or invoke the generated URL module. It
does not add public Python exports, dependencies, configuration keys, or
generated products. The full-feature example uses it to show two mounted
owners, shared source metadata, owner-specific navigation and destinations,
included and excluded selection evidence, and root error facts.

Route Explain reuses this graph and declaration evidence through the shared
generated-dispatch projection. It reports navigation declarations but never
evaluates their request-time values or changes dispatch. Application
composition remains a separate boundary. No consumer may create a
competing scanner, matcher, URL-helper model, or mounted-source selection
surface.

## Layout map projection

The layout-map projection reuses `RouteInventoryRow` occurrences for ordinary
and selected mounted layouts and for every canonical page, fragment, and
action. It does not require the URL-helper plan, add helper expressions, or
rescan mounted sources. Page and action rows carry source positions from one
private `_selected_layouts` helper owned by `_route_graph.py`; generated
dispatch imports that same helper. Fragments carry an empty chain because
their rendering boundary is explicitly layout-free.

The display tree is an ephemeral presentation value built from final live URL
path segments. It stores no route ownership, matching, normalization,
inheritance, handler, template, or runtime decision. At one path it orders
effective layouts by the first canonical endpoint chain that contains them,
rejecting contradictory precedence, then emits pages, fragments, actions, and
child path nodes. Static children precede dynamic children with the accepted
inspection comparator.

The renderer uses fixed ASCII connectors and application-relative POSIX source
positions. It assembles and ASCII-encodes the complete map before stdout is
written. Projection, reconciliation, ordering, encoding, and stdout failures
are command-specific `PYGANINI017 route-inspection` failures; graph failures and
`routes list` URL-helper failures retain their existing owners.

## Route Explain matching boundary

Route Explain reuses `_groups()`, `_group_methods()`, and
`_method_endpoints()` from `_dispatch_generation.py`. The generator and
explanation therefore share the same canonical endpoint grouping, graph order,
method union, and method-to-endpoint projection. For each group, explanation
constructs the existing `PathPriorityRoute` with a private never-called
endpoint and calls only `matches()` with the minimal HTTP scope. Starlette owns
path compilation and capture; `PathPriorityRoute` promotes a method-partial
match to path ownership; graph order preserves static-before-dynamic priority.

The first path match is classified as matched or 405 before later groups are
examined. A supported HEAD request selects the GET endpoint for evidence but
does not execute it. A missing group is 404. Matched output projects the
canonical endpoint's ordered parameters, handler, shared declaration and
implementation evidence, live owner, mount, selected source path, root error
facts, and `_selected_layouts()` chain. Fragments
use an empty layout tuple and actions retain the valid-Page caveat.

The explanation renderer quotes user-controlled path and parameter strings with
the standard library's JSON string primitive, assembles all lines, and ASCII
encodes before one stdout write. 404 and 405 append root error-render facts
and remain complete stderr outcomes with no stdout; reachable grouping,
reconciliation, layout, encoding, and output
failures use the command-specific `PYGANINI017 route-inspection` boundary.

This is a presentation branch over canonical graph and dispatch facts, not a
second matcher, route tree, router, registry, inventory order, URL-helper
model, generated product, runtime hook, or public API. Layout, refs, and
render-unit byte contracts remain independent and unchanged.
Runtime marker projection is owned by generated dispatch, not this source-only
inspection branch. `pyganini.render_units.v1` remains unchanged and contains no
error presentation, component, overlay, or runtime occurrence fields.
