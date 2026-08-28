# Generated URL Interfaces Architecture

Pyganini generates one typed application URL module at
`app/_pyganini/urls.py`. The module is a projection of the immutable
`RouteGraph`, not a second route model. The same graph and canonical
`iter_endpoints()` view feed dispatch and URL generation before the existing
generation owner compares or mutates `app/_pyganini`.

## Ownership and lifecycle

`src/pyganini/_url_generation.py` owns the URL-specific projection. Its one
private `_url_helper_projection(graph)` consumes `iter_endpoints(graph)`,
builds the live transient helper tree and mounted identity catalog, validates
helper names, and provides final-path helper expressions. `url_plan(graph)`
renders one `GeneratedArtifact` for `app/_pyganini/urls.py` from that projection;
source inspection consumes the same projection and emits no artifact.
`_cli._run()` combines the artifacts in this order:

```python
(*bootstrap_plan(), *dispatch_plan(route_graph), *url_plan(route_graph))
```

`_generation.py` remains the sole owner of normalized artifact validation,
ownership checks, stale comparison, atomic replacement, obsolete cleanup,
partial-failure reporting, and the recursive no-write guarantee of `check`.
There is no URL manifest, persisted helper tree, runtime registry, URL scanner,
or additional writer.

Graph construction and URL projection import no application code. Navigation-
bearing generated modules also import Pyganini's private pure URL-segment helper;
they do not import application modules or construct a second path binder. The
generated module otherwise imports only `dataclasses`, `typing.overload`, and
`urllib.parse` from the standard library. It contains the ownership marker, a
concise module docstring, `__all__ = ("mount_urls", "urls")`, annotated `mount_urls` and
`urls` values, private slotted immutable node types, and fully annotated
generated accessors.
`app/_pyganini/__init__.py` stays neutral; `pyganini` gains no URL export.

## Helper tree

The transient tree deduplicates by normalized endpoint path, regardless of
endpoint kind or method. Static segments become attributes after browser
hyphens are changed to underscores. A dynamic `{user_id}` segment becomes
`by_user_id(user_id: str)`. Static children sort deterministically and the
dynamic child follows them. A node has a read-only `.path` property only when
its complete path owns an endpoint.

Kit endpoints use this same route-shaped helper projection. The URL generator
does not add a kit namespace or shared implementation name. Each live owner
receives the helper paths for the surfaces it declares. Mounted source
identities are exposed only through the generated `mount_urls` catalog; its
`bind(owner)` operation returns a fresh immutable helper tree for the exact
source declarations selected by that owner's `route_mount(...)`. Selection is
declared by `route_mount(...)`, not supplied to `bind(...)`. The canonical
`iter_endpoints()` view supplies those endpoints just as it does for route-local
declarations.

The synthetic root helper owns `with_base_path(base_path: str) -> <private root
type>`. If the graph owns `/`, `urls.root.path` is the root endpoint value. The
module-level `urls` value itself is the root helper surface, so it can expose
`with_base_path()` and all route-shaped children. Empty graphs still emit this
typed root surface without route attributes.

Each generated value is a frozen slotted dataclass carrying only its normalized
quoted base prefix and its bound local path. Static properties create typed
children. Dynamic methods validate and quote one value before creating the
typed child. Mounted binding validates the owner key, then creates the owner's
selection-filtered rebased tree. No operation reads the filesystem, imports
a route, checks the inbound matcher, or caches request state.

## Validation and quoting

Dynamic values are decoded one-segment strings. Generated runtime code rejects,
in order, non-strings, empty values, `.` and `..`, slash or backslash, ASCII
control characters, and invalid UTF-8 text. Accepted values use
`urllib.parse.quote(value, safe="")`. This quotes literal percent text and
reserved characters while preserving the standard URL unreserved characters.

Base paths are decoded prefixes selected by application code. Empty input and
`/` mean no prefix. Other input is given one leading slash, trailing slashes
are removed, repeated internal empty segments are rejected, and each segment
uses the same validation and quoting rules with one-based
`base_path segment <index>` evidence. Base paths never include scheme,
authority, host, port, or proxy-header policy.

The slash rejection is intentional. Starlette matching consumes decoded
`scope["path"]`; a helper that percent-encoded a slash would produce a path
that current Pyganini inbound dispatch cannot claim to match. A later inbound
routing child must change that contract before slash-containing values can be
supported.

## Helper-only diagnostics

Inbound route validity does not guarantee a valid Python helper surface. The
URL generator reports `PYGANINI016 url-interface` before generated-state
inspection, comparison, staging, replacement, or cleanup when it finds:

- `root` or `with_base_path` at the generated root;
- `path` at any namespace;
- a static segment or dynamic parameter that is a Python hard keyword;
- static and dynamic children that map to the same `by_<param>` member; or
- distinct paths or other generated public members that map to one helper
  expression; or
- navigation-reserved `route_pattern`, `destinations`, or `trail_keys` members
  colliding with live route children or generated collections; or
- destination and trail-key names that normalize to Python keywords or another
  invalid generated member.

The generator retains source position, normalized path, helper expression,
conflicting member, and the other owner. Independent reachable issues are
deduplicated and sorted by source path, line, column, normalized path, and
message. The main diagnostic uses the existing `GenerationError` rendering
shape and remaining evidence is indented detail. No suffix, alias, dictionary,
item-access fallback, or second access style is invented.

Existing `PYGANINI009` through `PYGANINI011` graph failures still occur first. URL
helper failures are generation-plan failures for the URL projection and do not
change route declarations, graph schema, inbound dispatch, rendering, or
handler contracts. `pyganini routes list` reports the same `PYGANINI016` before any
inventory output and never imports the generated URL module.

For a graph without Navigation metadata, `urls.py` remains on the existing
renderer path byte-for-byte. A navigation-bearing plan uses immutable callable
target objects, typed `trail_keys`, and live source destination values without
changing the generated product count or public `urls`/`mount_urls` exports.
Unbound destination selectors are resolved by the canonical graph, so a static
segment whose generated member begins with `by_` remains static when it is a
valid live target. A dynamic parameter named `self` retains its call syntax
through a non-conflicting generated receiver.

## Typing and host composition

The generated `.py` module is the runtime and static surface; no `.pyi` is
generated. Its private class types remain visible through inference from
`urls` and `mount_urls`, while application code imports only those two values.
Mypy and Pyright proof
covers static access, one-at-a-time dynamic binding, exact keyword parameter
names, bound child access, base-path rebinding, missing and unknown arguments,
wrong argument types, unknown attributes, and the absence of `.path` on a
namespace-only node. It also covers owner-specific mounted overloads,
selection-filtered members, excluded-source absence, and invalid owner keys.
Runtime tests import the same generated module and compare the checked paths.

Host composition remains application-owned. A handler or host callback selects
the effective decoded `request.scope["root_path"]` and calls
`urls.with_base_path(...)` explicitly. The same helper works in Starlette and
FastAPI mounts; Pyganini does not add a request global, proxy policy, host adapter,
Jinja global, or implicit template context value. A template receives a URL
surface only when application code passes it in `Page`, fragment, or layout
data.

Request Navigation normalizes that same scope value through the private pure
binding owner. This keeps canonical navigation and explicitly bound generated
destinations in one prefix space without changing generated module bytes,
signatures, route matching, or graph-local `route_pattern` values.
