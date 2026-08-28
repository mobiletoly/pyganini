# Template Inspection

Pyganini can add development-only boundaries around rendered Jinja units. The
generated router is off by default and production construction remains:

```python
router = create_router()
```

Select a typed mode explicitly when constructing a development router:

```python
from pyganini import TemplateInspectionMode

router = create_router(template_inspection=TemplateInspectionMode.COMMENTS)
```

`COMMENTS` emits paired `pyganini:start` and `pyganini:end` HTML comments around
pages, selected layouts, fragments, and rendered error presentation. `OVERLAY`
emits the same comments. It does not inject or mount JavaScript. Applications
may mount `pyganini.browser.create_app()` and visibly include
`browser.TEMPLATE_INSPECTOR_HELPER_PATH` only for their development overlay.

Templates can identify two explicit nested units without adding a component
registry:

```jinja
{% call pyganini_inspection.component("Contact directory") %}
  ... ordinary HTML and Jinja ...
{% endcall %}

{% call pyganini_inspection.fragment("/table") %}
  {% include "mounts/contact_directory/table.jinja" %}
{% endcall %}
```

The fragment path is source-local and must name a declared fragment available
from the same selected route source. The component label is stripped and must
not be empty. `pyganini_inspection` is reserved in page and fragment context.
Both call blocks invoke their body exactly once. In `OFF`, their body bytes are
returned unchanged.

Markers contain only deterministic graph-local route, template, declaration,
owner, handler, layout, and mount evidence. They contain no request host,
query, dynamic path value, or ASGI `root_path`. Metadata is UTF-8
percent-encoded and the unit ID is a SHA-256 identity of the unescaped static
evidence. Direct Starlette responses remain unmarked.

The optional browser helper reads valid nested comment pairs from the complete
document, including an outer root layout around the doctype. It rejects
noncanonical encoding, malformed or misplaced labels, mismatched kind/surface
values, and IDs that do not match the decoded marker evidence. Its visible
`All`, `Off`, and `Next` buttons use native keyboard behavior; `Next` has the
accessible name `Next render unit` and selects one drawable unit with each
activation, including directly from `Off`. Selection follows one live drawable
marker occurrence and resets if that occurrence is removed. The helper redraws
after resize, scroll, HTMX swaps and settles, and application DOM mutations;
stale helper nodes are removed on every redraw. Re-executing the resource
cleans up either a pre-body startup callback or the prior observer, listeners,
pending detail-dismiss timeouts, animation-frame work, and helper-owned DOM.

If the document contains no valid marker pair with a connected, non-empty
drawable range, the helper creates no controls, frames, handles, detail panel,
or other overlay DOM. Losing the last drawable unit removes existing UI and
resets selection. A later application mutation that makes a valid unit
drawable recreates the controls and unit UI.

Moving focus or the pointer from a unit handle into its detail panel keeps the
panel operable. The optional copy control copies the displayed template source
position when the Clipboard API is available. Clipboard lookup, synchronous
failure, and rejected promises are silent and do not create a page error.
Long detail metadata remains inside the viewport at the documented small-screen
size.

The application owns the mode source, development authentication, mount and
URL, CSP, cache layers, and deployment exposure. Pyganini does not read an
environment variable or infer development mode.
