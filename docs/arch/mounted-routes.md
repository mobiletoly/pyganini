# Mounted Route Subtrees Architecture

Mounted route subtrees reuse one filesystem-shaped source tree below
`app/mounts` for multiple live owners. They extend the existing route graph,
dispatch, URL, and rendering products; they do not create a second route model,
runtime registry, or application-policy boundary.

## Declaration and source ownership

`_declarations.py` owns the four public mounted names:

- `KitRouteMount[K]`
- `MountRoute`
- `route_mount(...)`
- `mount_route(...)`

`route_mount` is valid only in a live `app/routes/**/route.py`. It requires one
creator, one lowercase `mount` identity, and an optional literal tuple of
`mount_route(path)` values. A missing `routes` value means every source
declaration. The path is `/` or a slash-separated canonical source route
pattern with static or dynamic segments. The creator is owner-specific and
produces the source kit type `K` for selected page, fragment, and non-captured
action handlers using `(kit, request)`; captured actions use `(kit, request,
body)` or `(kit, request, form)`.

A referenced source route below `app/mounts/<mount>` uses the exact creator-free
`route_kit(...)` grammar with colocated endpoint templates. It has no live
route identity, `template_root`, authentication, authorization, middleware,
sessions, persistence, dependency injection, or dependency scope. Direct live
route kits remain the separate `route_kit(create=..., template_root=...)`
contract.

Navigation defaults are source-owned `RouteNav` facts. Source declarations
cannot own destinations; live owners attach destination edges to selected
`MountRoute` values.

## Containment and graph construction

`ProjectPaths.mounts` records an optional regular `app/mounts` package. The
route graph scanner enters only referenced source identities and holds the
same no-follow, contained package directories used for `app/routes`. It
validates package markers, route and layout convention files, endpoint and
layout templates, UTF-8, static names, `by_<param>` names, and source
declarations. Unreferenced mount children are ignored and do not enter graph
inventory.

For each owner, expansion applies the exact selection allowlist to the source
declaration surface. It rejects unknown or duplicate selection paths and
records `MountOwner` and `MountedRouteBinding` evidence. A selected source
node is rebased below the live owner's final path; its parameters, endpoint
handlers, templates, owner, source route, and layout ancestry remain explicit.
Live outer layouts precede mounted inner layouts. Source paths and owner
positions remain available for diagnostics.

Expansion inherits a source navigation default when a selected `MountRoute`
omits `nav`; a non-`None` selection value replaces it. Selection destinations
replace the empty source destination set. The final node retains both effective
facts and source facts so runtime import validation can detect owner/source
drift. Excluded source declarations never contribute navigation, destination,
or accepted-key facts.

The immutable `RouteGraph` stores live nodes, mount owners, and mounted
bindings. `iter_endpoints()` is still the only endpoint derivation. Every
mounted endpoint carries owner, mount identity, source path, handler source,
rebased path, parameters, template, and layout evidence. Exact method/path
collisions and same-shape dynamic collisions are rejected after expansion;
static and dynamic siblings retain deterministic static-first order.

## Generated dispatch

`_dispatch_generation.py` emits one `app/_pyganini/asgi.py` artifact from the
canonical graph. It captures only selected source declarations, the live
owner's creator, source handlers, rebased route facts, and composed layouts.
The generated module validates the runtime `KitRouteMount` surface, exact
selection, live creator, creator-free source `KitRouteDef`, source handler
identity, callable signatures, and navigation selection values. It also emits
a type-only generic witness
linking one owner `K` to its source `KitRouteDef[K]`.

At request time, generated dispatch invokes the captured owner creator once and
the selected source handler once. It reads no filesystem, discovers no route,
registers no source, expands no declaration, and looks up no second graph.
The existing Starlette method grouping, static-first matching, sync/async
offload, response validation, rendering, and HEAD behavior remain in force.
One canonical graph produces one generated Starlette `Router`.

## Generated URL catalog

`_url_generation.py` emits the one `app/_pyganini/urls.py` artifact with exactly
these public values:

```python
__all__ = ("mount_urls", "urls")
```

`urls` is the live route-shaped helper tree. `mount_urls` is a generated nested
identity catalog. An identity referenced by one owner exposes one direct typed
`bind(owner: OwnerNode) -> BoundType` signature. An identity referenced by
multiple owners exposes one typed overload per accepted owner and one runtime
implementation. Binding validates the live owner key, preserves the owner's
local path and base prefix, and returns a fresh immutable helper tree containing
only the source endpoints selected by that owner's `route_mount(...)`
declaration. Selection belongs to `route_mount(...)`, not `bind(...)`; omitted
declaration selection means all source declarations.

Excluded source declarations have no member in the bound helper, no live graph
endpoint, no dispatch entry, and no later middleware input. There is no
unbound all-source helper tree and no shared implementation namespace in the
live `urls` value. Invalid owner keys fail closed.

The generated module performs no filesystem access, route import, request
lookup, or graph construction. `mount_urls` and `urls` are projections of one
graph and one canonical endpoint view, and both support the existing explicit
`with_base_path()` contract.

Source inspection reuses that graph and canonical endpoint view. It reports
selected mounted endpoints plus effective mounted layouts from the existing
`RouteNode.layouts` tuples, rebasing source-relative layout prefixes below each
live owner and deduplicating repeated ancestry. An exact `--mount` filter keeps
those mounted rows for every owner of the identity and omits ordinary outer
layouts and excluded source declarations. It does not rescan `app/mounts` or
import `mount_urls`.

## Rendering and boundaries

Mounted page templates are named from their source path, such as
`mounts/contact_directory/page.jinja`, and render with the existing synchronous
Jinja environment. Page composition is live outer ancestry followed by mounted
inner ancestry. Mounted fragments render without layouts. Application code
supplies URLs, data, and policy through the owner kit and templates.

Route Layouts and Route Explain inspect selected mounted occurrences from the
canonical final graph without changing mount ownership. Navigation and
destination generation use the accepted Navigation contracts: source nav
defaults are inherited by selected mounted routes, live owner selections may
override them, and destination edges remain live-owner data. Mounting a source
route tree does not mount a Starlette or FastAPI application and does not
transfer host middleware, authentication, sessions, persistence, or deployment
ownership.

Live route-tree middleware follows the same owner boundary. A selected mounted
endpoint inherits the root-to-owner chain from its live `route_mount(...)`
declaration; `app/mounts/**/middleware.py` is rejected and cannot add policy.
Two live owners of one source may therefore supply different compatible chains,
while methods sharing one normalized final path must agree before generation.
