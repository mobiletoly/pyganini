# Route Kit Architecture

Route kits extend the existing route declaration and dispatch contracts without
adding a second route model. The live route owner remains the source of URL and
surface ownership. The shared package supplies ordinary handlers and templates;
it has no registration side effect or route identity.

## Declaration facts

`_declarations.py` owns the frozen, slotted generic values
`KitRouteDef[K]`, `KitFragmentRouteDef[K]`, and `KitActionDef[K]`. The factories
are `route_kit`, `kit_fragment_route`, and `kit_action`. They reuse local path,
method, template filename, duplicate, page/index, and non-empty-surface
normalization. `template_root` is normalized as slash-separated lowercase
ASCII package components below `app`; it rejects private components,
`routes`, `_pyganini`, empty components, traversal, backslashes, absolute forms,
and non-ASCII text. Direct dataclass construction applies the same checks.

The public creator type is `Callable[[Request], K | Awaitable[K]]`. Kit page,
fragment, and action handlers carry the same `K` and accept
`(K, Request)` with the existing `PageRouteResponse`,
`FragmentRouteResponse`, and `RouteResponse` result aliases. No second public
handler-alias family is exported. `route()` retains its one-request contract
and rejects kit declaration values; `route_kit()` rejects local helper values.

## Static graph evidence

The AST parser accepts only exact unaliased imports of `route_kit`,
`kit_fragment_route`, and `kit_action`, one direct unannotated
`Route = route_kit(...)` assignment, literal keyword fields, literal tuples,
and the existing named handler forms. It records creator and handler source
bindings without importing application code. Calls, lambdas, chained or
computed references, aliases for constructors, forward local functions,
keyword expansion, star imports, and ambiguous rebinding fail with `PYGANINI010`.

`NormalizedRoute` retains one optional private kit binding containing creator
evidence and the normalized template root. `Endpoint` retains optional creator
evidence beside the existing handler, path, method, template, and layout facts.
`iter_endpoints()` is still the only endpoint derivation used by dispatch and
URL generation. No kit graph, registry, manifest, import discovery, or runtime
filesystem scan exists.

## Shared template containment

During graph construction, each declared shared template is resolved from the
held `app` directory through the existing no-follow directory abstraction. The
scanner checks every package component, its contained regular `__init__.py`,
the final regular template file, and UTF-8 decoding. Symlinks, reparse points,
unresolved paths, missing markers, non-directories, non-regular files, and
invalid UTF-8 fail with `PYGANINI009` before generated-state comparison or writes.
Each package marker is reopened through the held no-follow readable-file path,
so an unreadable marker also fails with localized `PYGANINI009` before generated
state is accessed.

The graph records both the complete source path and the package-relative Jinja
environment name. The template declaration position is retained separately as
declaration evidence. A shared template location never contributes layout
ancestry; layouts are selected from the live owner's route ancestry. The
existing Jinja environment contract therefore resolves shared names without a
custom loader, overlay, prefix registry, or fallback.

Generated request-time render diagnostics include that declaration position
alongside the template root, complete source path, environment name, handler
evidence, and live owner's layout chain.

## Controlled imports and generation

Generated `asgi.py` passes the retained creator and template-root evidence to
`load_route`. The import phase validates the runtime declaration kind, complete
surface, template values, creator identity, handler identities, and source
bindings. Creator diagnostics identify the creator module, symbol, binding,
source position, `callable role: kit creator`, and every affected kit
surface's kind, normalized path, methods, handler binding, symbol, module, and
source. Kit handler diagnostics use the existing selected-surface evidence plus
`callable role: kit handler`.

Callable classification is parameterized by role and arity. Creator callables
must accept one request argument. Selected kit handlers must accept
`(kit, request)` for pages, fragments, and non-captured actions; captured action
handlers must accept `(kit, request, body)` or `(kit, request, form)`. Async
generators, unsupported callable descriptors, partials with the wrong remaining
signature, and other signature failures remain `PYGANINI013`.
The creator is captured from the validated `KitRouteDef`; no application code
is invoked during generated-module import.

For each generated method, `_dispatch_generation.py` captures the selected
handler and, for a kit endpoint, the selected creator. A path group can combine
local and kit methods, so creator capture remains method-specific. At request
time `_dispatch.py` validates path-parameter evidence, invokes the selected
creator once, awaits its result when needed, captures request data for an opted-in
action, invokes the selected handler once with `(kit, request)` or
`(kit, request, body)` or `(kit, request, form)`, and sends the result through
the existing response and rendering contract. Local handlers keep the
one-request path.

Creator and handler invocation use the same independent callable model as local
handlers: async calls stay on the ASGI event loop; sync calls use AnyIO's
default worker limiter with `abandon_on_cancel=True`; returned awaitables are
awaited after a sync call returns. Context variables and application exception
identity are preserved. There is no kit cache, cleanup callback, generator
dependency, thread-affinity promise, or request-body materialization.

## Invariants and diagnostics

- The live route owner owns URLs, layout ancestry, and its declared surface.
- A shared implementation owns no route registration or route identity.
- One generic `K` links a creator to all handlers in one declaration.
- `route_kit` templates use one explicit package root and the existing loader.
- `iter_endpoints()` remains canonical for dispatch and URL helpers.
- `PYGANINI009` owns shared-template filesystem evidence and `PYGANINI010` owns
  static grammar and normalization failures.
- `PYGANINI012` owns runtime declaration, import, and binding drift;
  `PYGANINI013` owns creator and handler callable validation; `PYGANINI014` and
  `PYGANINI015` retain response and rendering ownership.
- The public response model, dependency set, generated filenames, Python
  support lines, check-mode immutability, and host mounting contracts do not
  change.

Mounted route subtrees use the separate `KitRouteMount`, `MountRoute`,
`route_mount`, and `mount_route` contracts. Their creator-free source kits,
exact selection, source containment, rebasing, owner-bound URL catalog, and
layout composition are defined in [Mounted Routes](mounted-routes.md).
The source-only [route inspection](../user/route-inspection.md) command
reports selected kit endpoints and effective mounted layouts from the same
graph; it does not inspect runtime kit values or import shared modules.
Navigation, dependency injection, middleware, authentication, and
synchronization remain outside this route-kit contract. Explicit sync
request-data materialization is an action-owned extension of the shared
handler contract; it preserves creator ordering, mounted-source capture facts,
and the same canonical graph.
