# Mounted Route Subtrees

Mounted route subtrees reuse one filesystem-shaped route source under one or
more live route owners. The source tree lives below `app/mounts/`; the live
owner stays below `app/routes/` and keeps the final URL prefix, outer layouts,
request-scoped creator, data, and application policy.

## Source tree

`app/mounts/` is optional. A referenced source is a regular Python package with
route-local files:

```text
app/
  mounts/
    __init__.py
    contact_directory/
      __init__.py
      handlers.py
      layout.py
      layout.jinja
      page.jinja
      route.py
      create/
        __init__.py
        handlers.py
        route.py
        directory.jinja
      by_id/
        __init__.py
        handlers.py
        page.jinja
        route.py
```

The source route files use creator-free `route_kit(...)` declarations. Their
templates are colocated and must be regular UTF-8 files below the source
package. A mounted source has no live URL, creator, outer layout, middleware,
authentication, authorization, session, persistence, dependency injection, or
dependency scope of its own.

```python
from pyganini import RouteNav, kit_fragment_route, route_kit

from .handlers import page, table

Route = route_kit(
    page=page,
    template="page.jinja",
    fragments=(kit_fragment_route("/table", table, template="table.jinja"),),
    nav=RouteNav(label="Directory"),
)
```

Mounted source declarations may set a canonical `nav=RouteNav(...)` default
but may not declare destinations below `app/mounts`. Live owners own the
destination edges.

The value-level `create` argument is optional so this source declaration is
valid. Static graph construction still requires `create` for a direct live
route kit and rejects `create` and `template_root` below `app/mounts/`.

## Live owner and selection

The live owner declares the exact source identity and creator:

```python
from pyganini import mount_route, route_mount

Route = route_mount(
    create=create_users,
    mount="contact_directory",
    routes=(mount_route("/"), mount_route("/create"), mount_route("/{id}")),
)
```

Each selected `mount_route` may replace the source navigation default and own
live destinations. An omitted `nav` inherits the source default; there is no
clear operation in this child:

```python
from app._pyganini.urls import urls
from pyganini import RouteNav, mount_route, route_mount, to

Route = route_mount(
    create=create_users,
    mount="contact_directory",
    routes=(
        mount_route(
            "/",
            nav=RouteNav(label="Contacts"),
            destinations=(
                to("contact-detail", urls.users.by_id, trail_key="from-contacts"),
            ),
        ),
        mount_route("/{id}"),
    ),
)
```

`KitRouteMount`, `MountRoute`, `route_mount`, and `mount_route` are the public
mounted-subtree names. `mount` uses lowercase ASCII package components joined by
`/`, so `reports/audit` maps to `app/mounts/reports/audit/`.

Omitting `routes`, or passing `routes=None`, selects every source declaration.
An explicit tuple selects exactly those source route patterns and all surfaces
declared by each selected declaration. It does not select descendants,
ancestors, or layouts as declarations. Empty, duplicate, malformed, and missing
selectors fail before generated-state access. An excluded declaration has no
live node, endpoint, dispatch capture, URL helper member, or later middleware
input.

The owner creator accepts one `Request` and returns `K` or an awaitable of `K`.
Every selected source handler accepts `(kit: K, request)`. Put owner-bound URL
values, filtered data, labels, callbacks, CSRF values, and policy booleans in
that ordinary application-owned kit. Pyganini does not interpret or enforce those
values.

## URLs and layouts

The one generated `app/_pyganini/urls.py` module exports exactly `urls` and
`mount_urls`:

```python
from app._pyganini.urls import mount_urls, urls

app_urls = urls.with_base_path(request.scope.get("root_path", ""))
directory_urls = mount_urls.contact_directory.bind(app_urls.users)
page_url = directory_urls.path
table_url = directory_urls.table.path
create_url = directory_urls.create.path
detail_url = directory_urls.by_id("42").path
```

Mounted helpers remain plain, query-free source helpers. Navigation destination
helpers belong to the live owner URL node, for example
`urls.users.destinations.contact_detail("42").href`.

`mount_urls` is only a catalog of source identities. Its entry exposes `bind`,
not an all-source route tree. A source identity with one accepted owner has one
direct selection-specific `bind` signature. A source identity with multiple
owners has one selection-specific overload per owner. Binding an unrelated live
node fails with `ValueError`; an excluded member cannot be fabricated. Nested
identities are catalog members such as `mount_urls.reports.audit`.

Owner dynamic parameters are already bound by the URL node passed to `bind`.
Mounted dynamic parameters remain typed methods on the returned relative
helper. Base-path normalization, quoting, and slash/backslash validation are
the same as the live `urls` surface.

For a selected page, layouts are ordered as live outer ancestry from the root
through the owner, followed by mounted inner ancestry from the source root to
the selected source route. Fragments remain layout-free. The source layout does
not replace the live owner's layout.

## Boundaries and example

Generation scans each referenced source once, builds one canonical final
`RouteGraph`, and generates one ASGI `Router` and one URL module. Request-time
dispatch performs no filesystem scan, source registration, route expansion, or
second graph lookup.

The full-feature example mounts one contact-directory source under `/users` and
`/settings/users`. The users owner selects the source root declaration (page
and table), create declaration, and detail declaration with full data and
mutation/CSRF policy. The settings owner selects only the source root
declaration, receives filtered read-only data, and has no create or detail
helper. Both owners retain different live layouts and share the mounted inner
layout.

The source-only [route inspection](route-inspection.md) command reports
selected endpoints and effective mounted-layout occurrences for every live
owner. An exact `--mount` filter also reports excluded source declarations as
non-live diagnostic rows while omitting ordinary outer layouts. `routes
explain` matches only endpoints selected into
the final graph and reports the live owner position, mount identity, selected
source declaration path, and outer-to-inner layout evidence. The same source
mounted below two owners produces distinct explanations; an excluded source
declaration has no final path and returns 404 rather than appearing as an
alternative. Mounted navigation inherits source defaults or uses live owner
selection overrides, while destination edges remain owner-owned and trails use
the live owner path. Application-composition middleware, framework
authentication, authorization, sessions, persistence, and dependency injection
remain explicit application or successor-child boundaries.

For a smaller demonstration, the [Kit routes example](../../examples/kit_routes)
mounts `app/mounts/reports` below `/admin/reports` and `/user/reports`. Both
owners select the source root page and table fragment. Only the admin owner
selects `/audit`, so `mount_urls.reports.bind(urls.user.reports)` has no
`audit` member and the unselected live path returns 404.
