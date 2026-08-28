# Pyganini User Documentation

Pyganini provides an installable package, static route-source validation,
project-root selection, deterministic generated Starlette dispatch, typed
generated URL interfaces, and final-asset fingerprinting.

- [Installation](installation.md) covers Python support, package installation,
  runtime dependencies, and host ownership.
- [Project layout](project-layout.md) covers the application marker, fixed
  source and generated paths, and file ownership.
- [Command line](cli.md) covers generation, non-writing checks, root selection,
  output, diagnostics, and exit codes.
- [Assets](assets.md) covers final build projection, fingerprinted output,
  generated lookup, commands, cleanup, host composition, and development flow.
- [Bounded client islands](client-islands.md) covers explicit application-owned
  roots, lifecycle cleanup, JSON policy, and build ownership.
- [Route inspection](route-inspection.md) covers source-only declaration,
  implementation, navigation, mounted-selection, layout, and error-render
  evidence in the deterministic table and `pyganini.routes.v1` JSON payload.
- [Routes](routes.md) covers live route packages, declarations, path mapping,
  layouts, and static validation.
- [Route middleware](middleware.md) covers live route-tree middleware,
  ordering, mounted-owner scope, diagnostics, and host boundaries.
- [Error composition](errors.md) covers the optional generated-route
  `RouteErrorHandler`, callback precedence, response contracts, and host
  ownership.
- [Route kits](route-kits.md) covers shared implementations, typed kit values,
  owner-specific URLs, shared templates, and invocation boundaries.
- [Mounted route subtrees](mounted-routes.md) covers reusable filesystem-shaped
  source trees, exact selection, owner-bound URLs, and mounted layout order.
- [Navigation](navigation.md) covers request-local trails, dynamic labels,
  typed destinations, alternate keys, Back, return safety, and mounted
  ownership.
- [Generated URL interfaces](urls.md) covers typed route-shaped paths, dynamic
  values, explicit base paths, and the query and request-context boundaries.
- [Rendering and responses](rendering.md) covers Jinja environments, pages,
  layouts, fragments, render values, and direct Starlette responses.
- [Server-Sent Event helpers](sse.md) covers deterministic UTF-8 wire framing,
  comments, reconnection headers, Starlette streaming, and application-owned
  operational policy.
- [Browser helpers](browser.md) covers the optional fixed-resource app, named
  SSE event swaps, template overlay delivery, explicit mounting, and cache
  revalidation.
- [Template inspection](template-inspection.md) covers typed development modes,
  deterministic render markers, explicit Jinja call blocks, and the optional
  browser overlay.
- [HTMX and async forms](htmx.md) covers visible attributes, generated URL
  values, header helpers, Starlette form parsing, uploads, and validation.
- [CSRF helpers](csrf.md) covers the optional signed-cookie helper, visible
  form and HTMX values, validation ordering, and application-owned policy.
- [Full-feature example](../../examples/full_feature) is a runnable downstream
  contact-directory application showing how the current public surfaces fit
  together under an application-owned Starlette host.
- [React island](../../examples/react_island) and
  [Svelte island](../../examples/svelte_island) are independent downstream
  proofs without a Pyganini client runtime.

Route declarations, their static graph, generated request dispatch, generated
URL values, mounted route subtrees, request-local navigation, route-local and
shared-kit Jinja rendering, the source-only route inventory, the async HTMX
form workflow, explicit immutable sync-action request data, and final asset
fingerprinting are implemented.
Automatic client response policy, CSRF enforcement, storage, total request-body
limits, and error presentation policy remain application-owned. Applications
may opt into the reusable `pyganini.csrf` helper without giving Pyganini ownership of
those policies.

Applications may also opt into the narrow pyganini.sse wire helper. It owns typed
event validation, deterministic UTF-8 framing, and Last-Event-ID header
retrieval only. Starlette and the application continue to own response
streaming, authorization, replay, cleanup, cache policy, and deployment.
The separate `pyganini.browser` helper remains opt-in and application-mounted.
Runtime template inspection is also opt-in; generated routers emit no markers
unless an application passes a non-off `TemplateInspectionMode`.
