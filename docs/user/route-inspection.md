# Route inspection

Pyganini can list the accepted static route inventory without reading generated
files or importing application code:

```text
pyganini routes list
python -m pyganini routes list
pyganini routes list --app-root /path/to/application
pyganini routes list --mount contact_directory
pyganini routes list --json
pyganini routes layouts
pyganini routes layouts --app-root /path/to/application
pyganini routes explain /users/42
pyganini routes explain --method HEAD /users/42
pyganini routes explain 'https://example.test/users/42?view=full#details'
pyganini routes refs
pyganini routes refs --json
pyganini routes render-units
pyganini routes render-units --json
```

The command selects the application root with the same explicit or fallback
rules as `generate` and `check`, builds the one static `RouteGraph`, validates
the one generated URL-helper projection, and renders the result. It does not
require `app/_pyganini` to exist or be current. It does not import route,
handler, layout, generated, or other application modules, and it does not
write, compare, clean, or inspect generated state.

`routes explain` is a separate source-only operation over one target. It uses
the same root selection and canonical graph, but does not build the URL-helper
projection. It extracts a path from an absolute path or hierarchical absolute
URL, removes only raw query and fragment text, and strictly percent-decodes the
complete path once as UTF-8 before matching it as ASGI `scope["path"]`.

## Render-unit inspection

`pyganini routes render-units` is a source-only report of declared template-backed
render capability:

```text
pyganini routes render-units [--app-root PATH] [--json]
python -m pyganini routes render-units [--app-root PATH] [--json]
```

It iterates the canonical `iter_endpoints()` view and emits one row only when
the endpoint retains a non-empty Jinja template declaration. Pages, fragments,
and actions remain distinct. Template-less endpoints, including direct
Starlette response surfaces, and unselected mounted declarations do not
appear. Layout markers are supporting evidence rather than independent rows.

The deterministic text header is:

```text
KIND  METHOD  ROUTE  TEMPLATE  TEMPLATE_SOURCE  SOURCE  OWNER  MOUNT  SOURCE_PATH  LAYOUT_MODE  EFFECTIVE_LAYOUTS
```

`METHOD` contains the endpoint's exact canonical methods. `TEMPLATE` is the
retained Jinja environment name, and `TEMPLATE_SOURCE` is its application-
relative source position. `SOURCE` and non-local `OWNER` use
`path:line:column`; ordinary redundant owners, missing `MOUNT`, and missing
`SOURCE_PATH` display as `-`. `EFFECTIVE_LAYOUTS` is an outer-to-inner list of
`<environment-name>@<layout-marker-position>@<template-source-position>`
values, or `[]` when empty.

Page rows use `layout_mode=page` and show the complete selected layout chain.
Fragment rows use `layout_mode=none` and always show `[]`. Action rows use
`layout_mode=page-result`: the displayed chain is available only when the
action returns `Page`; a `FragmentResponse` and a direct `Response` do not use
it. This is static declaration and layout evidence, not runtime observation.

`--json` writes one deterministic, two-space-indented, ASCII-escaped
`pyganini.render_units.v1` object with the keys `schema` and `render_units`.
Each row contains `kind`, `methods`, `route`, `template`, `source`, `owner`,
`mount`, `source_path`, `layout_mode`, and `effective_layouts`. Template
objects use `name` then `source`; positions use `path`, `line`, then `column`;
layout objects use `source` then `template`. Missing mount and source-path
values are JSON `null`. Empty results succeed with the complete text header or
an empty JSON array.

The command builds exactly one source-only graph and reuses graph-owned
`_selected_layouts()` for page and action evidence. It does not read or write
`app/_pyganini`, import or execute application code, load, parse, or render Jinja,
trace includes or inheritance, validate URL helpers, or inspect handler
results. Unknown, abbreviated, misplaced, and positional arguments return `2`
before root selection. Root and graph failures retain their existing
diagnostics. Projection, encoding, and stdout failures return `1` with:

```text
pyganini routes render-units: PYGANINI017 route-inspection: <message>
```

## Direct HTMX references

`pyganini routes refs` is an optional, read-only source inventory for direct HTMX
request attributes in graph-selected Jinja files:

```text
pyganini routes refs [--app-root PATH] [--json]
python -m pyganini routes refs [--app-root PATH] [--json]
```

It recognizes exactly `hx-get`, `hx-post`, `hx-put`, `hx-patch`, `hx-delete`,
and `data-hx-get`, `data-hx-post`, `data-hx-put`, `data-hx-patch`,
`data-hx-delete`. It derives roots from graph-retained template evidence:
ordinary `app/routes`, selected `app/mounts/<identity>` source trees, and
explicit shared route-kit template roots. Nested roots are collapsed. All
regular `.jinja` files below a selected root are scanned in deterministic
app-relative POSIX order, including unreferenced files; outside files are not
scanned.

The scanner masks standard Jinja syntax through the public `Environment.lex()`
token stream, parses only an isolated attribute expression with public
`Environment.parse()`, and delegates start-tag and attribute handling to
Python's standard-library `HTMLParser`. It does not render, import, execute,
follow includes or inheritance, infer ancestor HTMX attributes, evaluate
application values, or inspect `href`, form actions, form methods, or custom
Jinja delimiters. Each source position is the start-tag line with fixed column
`1`.

Rows are classified as:

- `resolved` for one exact method/path endpoint or one canonical generated
  `urls...path` helper shape;
- `unmatched` when a literal path has no exact endpoint for the request method,
  including an unknown path, or when a canonical helper shape exists only for
  another method;
- `dynamic` for application-owned or unsupported expression values;
- `external` for hierarchical or protocol-relative external URLs; and
- `invalid` for empty, relative, malformed, or invalid-helper values.

The text table begins with:

```text
STATUS  METHOD  ROUTE  KIND  ATTRIBUTE  SOURCE  VALUE
```

`ROUTE` is the matched or unmatched route, `KIND` is the matched endpoint kind,
`ATTRIBUTE` is the parser-normalized supported name, `SOURCE` is
`app-relative/path.jinja:line:1`, and `VALUE` is the normalized attribute
value. Values containing whitespace, control text, or non-ASCII text use JSON
string quoting. Duplicate attributes remain duplicate rows.

`--json` writes one deterministic two-space-indented `pyganini.refs.v1` object:

```json
{
  "schema": "pyganini.refs.v1",
  "references": []
}
```

Every reference contains `status`, `method`, `route`, `kind`, `attribute`,
`source`, `value`, and `matched`. Resolved matches retain endpoint `path`,
`kind`, `methods`, source and owner positions, mount evidence, selected
`source_path`, and the canonical helper expression. All JSON keys are present;
missing route, kind, and match values are `null`.

Argument errors return `2` before project selection. Root, graph, and URL-helper
failures retain their existing diagnostics. Selected-root, read, UTF-8, Jinja,
HTML-parser, reconciliation, encoding, and output failures return `1` with no
partial output and use:

```text
pyganini routes refs: PYGANINI017 route-inspection: <message>
```

`unmatched`, `dynamic`, `external`, and `invalid` rows are not command errors.
The command does not read `app/_pyganini`, change generated bytes, participate in
`pyganini check`, or alter request behavior.

## Text output

The default output is an ASCII table with this fixed header:

```text
KIND  METHOD  PATH  PARAMS  SOURCE  OWNER  MOUNT  SOURCE_PATH  DECL  NAME  TITLE  LABELS  NAV  TRAIL_KEYS  DESTINATIONS  INBOUND  IMPLEMENTATION  HELPER
```

`KIND` is `layout`, `page`, `fragment`, or `action` during normal live
inspection. Methods are comma separated; layouts show `-`. `PARAMS` contains
dynamic names in final path order. `SOURCE` and non-local `OWNER` use
`path:line:column` with application-relative POSIX paths. An ordinary owner is
the same position as its source and displays as `-`.

Endpoint rows report `DECL` as `route`, `route-kit`, or
`mounted-route-kit`. `NAME`, `TITLE`, and `LABELS` are static display metadata;
`NAV`, `TRAIL_KEYS`, `DESTINATIONS`, and `INBOUND` report effective graph-owned
navigation facts. `IMPLEMENTATION` is a compact JSON object containing the
handler binding, declaration, optional template, and optional request-data
evidence. Compact values use deterministic ASCII JSON. A missing value displays
as `-`. Layout rows have no declaration or implementation.

Rows use final static route paths and the same static-before-dynamic order as
dispatch. Prefix paths come before descendants; rows at one path sort by kind,
method, owner, source, mount, source path, and helper. The header is printed
for an empty or unmatched inventory.

Every text result ends with one `ERROR_RENDER` line containing the root page
template, root fragment template, and outer-to-inner root layout evidence.
These are static facts used by generated-route error composition; inspection
does not call the application error handler or render a template.

Endpoint helper values use the generated live `urls` spelling, for example:

```text
/                         -> urls.root.path
/users                    -> urls.users.path
/users/table              -> urls.users.table.path
/users/{id}               -> urls.users.by_id(id).path
/teams/{team_id}/reports  -> urls.teams.by_team_id(team_id).reports.path
```

Layouts have no helper. A mounted endpoint keeps the live owner position and
the selected source declaration path. Mounted layout rows keep the live owner,
mount identity, and source-relative layout prefix after it is rebased below
that owner. Live outer layouts remain ordinary rows.

## JSON output

`--json` writes the versioned `pyganini.routes.v1` object with two-space
indentation, ASCII escaping, UTF-8 encoding, and one final newline:

```json
{
  "schema": "pyganini.routes.v1",
  "error_render": {
    "page_template": null,
    "fragment_template": null,
    "root_layouts": []
  },
  "routes": []
}
```

The top-level keys are always `schema`, `error_render`, then `routes`.
`error_render` contains structured page and fragment template evidence and the
root layout chain. Every route row keeps `kind`, `methods`, `path`,
`parameters`, `source`, `owner`, `mount`, `source_path`, and `helper`, then adds
`selection` and `declaration`. `selection` is `null` during normal inspection.
`declaration` is `null` for a layout.

An endpoint declaration contains its source, declaration kind, optional name
and title, sorted labels, effective navigation, accepted inbound trail keys,
outbound and inbound destinations, mounted ownership, and implementation.
Implementation evidence contains the endpoint kind, handler module, symbol,
binding and source, declaration surface, optional template, and optional
request-data declaration. Missing scalar or object values are JSON `null`;
labels, trail keys, destinations, inbound destinations, and layouts are always
arrays. Source positions always use `path`, `line`, then `column`.

## Mount filtering

`--mount` accepts one normalized lowercase ASCII mount identity, including
nested identities such as `reports/audit`. It retains only rows whose `mount`
is exactly that identity. The result includes selected endpoint and effective
mounted-layout rows for every live owner with `selection=included`. It also
includes one `kind=route`, `selection=excluded` row for each source route that
the owner did not select. Excluded rows retain source declaration evidence but
have no methods, helper, or endpoint implementation and are never live.
Ordinary outer layouts are omitted because they have no mount identity. Text
output appends a `STATUS` column. A valid unreferenced identity succeeds with
no route rows while still reporting global error-render facts.

An invalid identity is an argparse usage error and returns 2 before root
selection. Project, route-graph, and URL-helper failures return 1 and print
their existing diagnostics before any inventory output. A reachable inventory
or output-encoding failure uses:

```text
pyganini routes list: PYGANINI017 route-inspection: <message>
```

Expected failures print no traceback or partial inventory payload.

## Layout map

`routes layouts` uses the same source-only graph and renders one deterministic
ASCII tree over final live URL paths:

```text
pyganini routes layouts
```

It includes every effective ordinary and selected mounted layout occurrence,
page, fragment, and action. Pages and actions show the complete graph-selected
outer-to-inner layout chain. Fragments always show `layouts=[] (not wrapped)`;
actions show `(valid Page results only)`. Mounted entries retain their source
position, live owner position, mount identity, and selected source path. The
tree places static children before dynamic children, uses fixed ASCII
connectors, and ends with rules for declared-template `Page` results,
layout-free fragments, and direct `Response` results.

The command selects source paths and builds the canonical graph without
requiring or reading generated state. It does not validate URL helpers, import
application or generated modules, execute handlers, load Jinja, or write files.
It returns 1 for project or graph failures and for post-graph layout selection,
projection, encoding, or stdout failures. The latter use:

```text
pyganini routes layouts: PYGANINI017 route-inspection: <message>
```

Unsupported flags, positional arguments, and abbreviated options return the
argparse usage code 2 before project selection.

## Route explanation

`routes explain` accepts one absolute path or hierarchical absolute URL:

```text
pyganini routes explain <url-or-path>
pyganini routes explain --app-root PATH --method METHOD <url-or-path>
```

The default method is `GET`. An explicit method is trimmed, required to be a
non-empty ASCII HTTP token, and uppercased. Target and method errors are usage
exit 2 before root selection. Raw query and fragment text is ignored without
validation; encoded delimiters remain path data. `%2F` decodes to a separator,
while `%252F` decodes once to the literal dynamic value `%2F`. Repeated and
trailing slashes remain unchanged.

A matched explanation is one deterministic ASCII payload containing the
existing target and `MATCH` facts followed by `DECLARATION`, `IMPLEMENTATION`,
`ERROR_RENDER`, and `RULES` sections. Declaration evidence contains the same
kind, metadata, effective navigation, destinations, inbound destinations,
trail keys, and mount evidence as the matching list row. Implementation
evidence names the handler binding and source, declaration surface, optional
template, and request-data declaration. Error evidence names the root page and
fragment templates and the selected endpoint's possible error-page layout
chain; error fragments remain unwrapped.

Page and action chains are outer-to-inner; fragments report
`layouts=[] (not wrapped)`, and actions state that only valid `Page` results
use their displayed chain. `HEAD` selects the GET endpoint without executing
it and reports `dispatch_method=GET`. The rules state that route metadata is
display-only and excluded mounted candidates are not endpoints.

Matching uses generated-dispatch path priority and fixes the first matching
path before method selection. A static path can therefore return 405 instead of
falling through to a later dynamic path. A missing path, including a trailing
slash or repeated-slash mismatch, returns exit 1 with no stdout and a
`PYGANINI017 route-inspection` 404 diagnostic. An unsupported method returns exit
1 with no stdout and the same boundary plus the exact canonical `allowed` set.
Both diagnostics append the root error page, error fragment, and root layout
facts without printing a partial matched declaration.

The command remains source-only: it does not inspect generated files, import
application or generated modules, construct a `Request` or `Router`, load
Jinja, execute handlers, or write files. It is the URL/method selection
explanation surface; `routes list` remains the endpoint/helper inventory and
`routes layouts` remains the layout tree. Direct template references,
navigation HTML, host composition, and runtime tracing remain separate
boundaries.

## Boundaries

These commands report canonical endpoints, declaration and implementation
evidence, effective navigation edges, mounted selection, error-render facts,
effective layout occurrences, static page/action layout chains, or one
graph-local URL/method explanation. They do not assign behavior to metadata,
render navigation HTML, expose request-time navigation state, compose
middleware, or trace runtime requests. Generated `urls.py` remains the runtime
and typing surface; route inspection reports helper spelling but does not
import the module, and Route Explain does not evaluate helper ambiguity.
This command is not runtime instrumentation. It does not report rendered error
results, explicit component call blocks, browser state, or runtime marker
occurrences. Use [Template inspection](template-inspection.md) for the separate
opt-in runtime surface.
