# Bounded client islands

Most Pyganini interactions should remain server-rendered HTML with visible HTMX.
Use a client island only when one bounded interaction genuinely benefits from
rich local state. A normal form, fragment, or redirect is simpler when the
server can own the whole transition.

The application renders an explicit empty element with initial values and
generated action and navigation URLs in `data-*` attributes. Client code may
change only that element's descendants. Pyganini and HTMX continue to own the page,
layout, route tree, and ancestor replacement.

A reliable application bridge:

1. Mounts initially and through `htmx.onLoad`, skipping roots that already
   have retained framework handles.
2. Retains the React root, Svelte component, or equivalent handle.
3. Calls `htmx.process(root)` after rendering ordinary anchors, without a
   client router.
4. Listens for `htmx:before:cleanup`, aborts outstanding work, disposes the
   retained handle, and removes it from the application map.
5. Mounts a fresh component when Back returns server-rendered markup.

Prefer an HTML form and redirect when JSON adds no product value. If a bounded
editor uses `fetch`, the application owns the JSON shape, field validation,
errors, storage, and cache policy. Render the CSRF token visibly in a meta
element, send it in the chosen header, and validate it through the
application's guard before parsing or mutation.

The application owns Vite and frontend sources. Vite writes final files to
`assets/build`; `pyganini generate` fingerprints them into `assets/dist`.
The Starlette host serves only generated dist files and applies immutable
caching only to exact generated paths. Runtime assets remain local unless the
application accepts another network boundary.

Pyganini does not supply hydration, generated JavaScript, a component registry,
shared client state, a bundler, framework adapters, a development proxy,
browser reload, or a client router. See the deliberately independent
[React example](../../examples/react_island) and
[Svelte example](../../examples/svelte_island).
