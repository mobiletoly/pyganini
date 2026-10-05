# Template Inspection

Read this for locating the source behind rendered regions. Start with source
inspection when possible:

```bash
pyganini routes list
pyganini routes explain /users/42
pyganini routes layouts
pyganini routes refs --json
pyganini routes render-units --json
```

These commands consume static route evidence without executing handlers.
`refs` inventories direct HTMX request attributes in selected Jinja roots; its
resolved/unmatched/dynamic/external/invalid states are inventory, not universal
template correctness. Render units report declared template capability, not
runtime handler results or arbitrary includes. Neither command renders Jinja.

## Optional runtime markers

Create a development router explicitly:

```python
from pyganini import TemplateInspectionMode

from app._pyganini.asgi import create_router

router = create_router(template_inspection=TemplateInspectionMode.COMMENTS)
```

`COMMENTS` emits deterministic paired markers around rendered pages, layouts,
fragments, and error presentation. `OVERLAY` adds the same comments but does not
mount or inject JavaScript. To show an overlay, explicitly mount
`browser.create_app()` and include the app-prefixed
`browser.TEMPLATE_INSPECTOR_HELPER_PATH` only in development markup. OFF is the
default; Pyganini does not infer development mode from environment variables.

Explicit nested units can use the reserved inspection helper:

```jinja
{% call pyganini_inspection.component("User panel") %}
  <section>... ordinary HTML and Jinja ...</section>
{% endcall %}
```

`pyganini_inspection.fragment("/table")` can wrap an explicit include when that
source-local fragment is declared and available from the same selected source.
These blocks call their bodies once, including OFF mode. Do not overwrite
`pyganini_inspection` in render-value context.

Direct Starlette responses receive no markers. Static marker evidence excludes
request host, query, dynamic values, and `root_path`. Do not make application
behavior or tests depend on marker IDs, comments, or overlay DOM. The app owns
development exposure, access control, CSP, helper mounts, and URLs. An overlay
needs valid markers with connected drawable content before it shows controls.

See [Assets, development, and SSE](assets-dev-sse.md) for helper delivery and
[Validation](validation.md) for distinguishing static and runtime evidence.
