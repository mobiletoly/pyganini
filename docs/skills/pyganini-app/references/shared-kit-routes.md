# Shared Kit Routes and Mounted Subtrees

Use kits for concrete shared render implementations with owner-specific request
state, not as a dependency-injection container. Keep ordinary imports or local
adapters when they are enough. Every live URL remains owned by `app/routes`.

## Direct route kits

A live owner supplies one sync or async `create(request)` returning its ordinary
typed application kit. Shared handlers receive `(kit, request)`. The same kit
type must fit creator and selected handlers; annotate it for mypy and Pyright.

```python
from pyganini import kit_fragment_route, route_kit

from app.shared.reports import create_reports, page, table

Route = route_kit(
    create=create_reports,
    template_root="shared/reports",
    page=page,
    template="page.jinja",
    fragments=(kit_fragment_route("/table", table, template="table.jinja"),),
)
```

`app/shared/reports` must be a regular package with the declared templates.
It owns shared implementation, not URLs or layout ancestry. Live kit templates
need an explicit application-relative `template_root`; direct-response-only kits
omit it. Use `kit_action` for mutations, with the ordinary action path/method
rules. Captured request-data actions receive `(kit, request, body_or_form)`.

The creator runs once for the selected endpoint, with no cross-request cache.
Sync creators and sync handlers can run on different worker threads: do not
pass thread-affine resources between them. The kit may carry bound generated
URLs, data, callbacks, labels, and application policy values; Pyganini does not
interpret those values. A page uses live-owner layouts and a fragment has none.

## Filesystem-shaped mounted sources

Reusable route trees live below `app/mounts/<identity>`, with regular packages,
creator-free `route_kit` declarations and colocated templates. They cannot set
`create`, `template_root`, middleware, destinations, or root error templates.
Their handlers still receive the kit supplied by the live owner. Live ownership
uses the separate `route_mount`/`mount_route` concepts:

```python
from pyganini import mount_route, route_mount

from .handlers import create_reports

Route = route_mount(
    create=create_reports,
    mount="reports",
    routes=(mount_route("/"), mount_route("/audit")),
)
```

This example assumes those declarations exist in `app/mounts/reports`.
Omitted `routes` selects all source declarations. A literal selection tuple
selects exactly named declarations and all their surfaces, not their ancestors
or descendants. Excluded declarations have no endpoint or URL helper. A
child-only selection does not make the mount root dispatchable.

Bind source-relative helpers from the generated live-owner URL object:

```python
from app._pyganini.urls import mount_urls, urls

app_urls = urls.with_base_path(request.scope.get("root_path", ""))
report_urls = mount_urls.reports.bind(app_urls.admin.reports)
# For an owner selecting the source root and /audit:
index_path = report_urls.path
audit_path = report_urls.audit.path
```

The mount catalog exposes `bind`, not an unbound all-source helper tree. Pass
the bound helper through the kit for same-mount links; use application callbacks
for outside destinations. Do not bind from a raw path string or fabricate
excluded helpers. Dynamic owner parameters must already be bound.

Pages receive live outer layouts followed by mounted inner layouts; fragments
remain layout-free. Middleware and auth policy stay with live owners/host.
Use `pyganini routes list --mount reports` and `routes explain` to inspect
selection and ownership; regenerate after declaration/selection changes.
