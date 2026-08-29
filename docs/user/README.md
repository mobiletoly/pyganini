# Pyganini User Documentation

Start with the tutorial, then use the focused guides as references while you
build an application.

- [Getting Started](getting-started.md) builds a two-page application with a
  shared layout, a dynamic route, generated URL helpers, route inspection, and
  an application-owned Starlette host.
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
  evidence.
- [Routes](routes.md) covers live route packages, declarations, path mapping,
  layouts, and static validation.
- [Route middleware](middleware.md) covers live route-tree middleware, ordering,
  mounted-owner scope, diagnostics, and host boundaries.
- [Error composition](errors.md) covers the optional generated-route error
  callback, response contracts, and host ownership.
- [Route kits](route-kits.md) covers shared implementations, typed kit values,
  owner-specific URLs, shared templates, and invocation boundaries.
- [Mounted route subtrees](mounted-routes.md) covers reusable filesystem-shaped
  source trees, exact selection, owner-bound URLs, and mounted layout order.
- [Navigation](navigation.md) covers request-local trails, dynamic labels, typed
  destinations, alternate keys, Back, return safety, and mounted ownership.
- [Generated URL interfaces](urls.md) covers typed route-shaped paths, dynamic
  values, explicit base paths, and query and request-context boundaries.
- [Rendering and responses](rendering.md) covers Jinja environments, pages,
  layouts, fragments, render values, and direct Starlette responses.
- [Server-Sent Event helpers](sse.md) covers UTF-8 wire framing, comments,
  reconnection headers, Starlette streaming, and application-owned operational
  policy.
- [Browser helpers](browser.md) covers the optional fixed-resource app, named
  SSE event swaps, template overlay delivery, explicit mounting, and cache
  revalidation.
- [Template inspection](template-inspection.md) covers typed development modes,
  render markers, explicit Jinja call blocks, and the optional browser overlay.
- [HTMX and async forms](htmx.md) covers visible attributes, generated URL
  values, header helpers, Starlette form parsing, uploads, and validation.
- [CSRF helpers](csrf.md) covers the optional signed-cookie helper, visible form
  and HTMX values, validation ordering, and application-owned policy.

The [full-feature example](../../examples/full_feature) shows the public
surfaces in one application. The independent
[React](../../examples/react_island) and [Svelte](../../examples/svelte_island)
examples show bounded client islands without a Pyganini client runtime.
