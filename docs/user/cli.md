# Command Line

Installation provides the `pyganini` command and equivalent module execution:

```text
pyganini --help
pyganini --version
python -m pyganini --help
python -m pyganini --version
pyganini generate [--app-root PATH]
pyganini check [--app-root PATH]
pyganini assets dist [--app-root PATH]
pyganini assets check [--app-root PATH]
pyganini assets list [--app-root PATH] [--json]
pyganini assets clean [--app-root PATH]
pyganini routes list [--app-root PATH] [--mount MOUNT] [--json]
pyganini routes layouts [--app-root PATH]
pyganini routes explain [--app-root PATH] [--method METHOD] <url-or-path>
pyganini routes refs [--app-root PATH] [--json]
pyganini routes render-units [--app-root PATH] [--json]
```

`--version` prints the installed distribution version. Command-line usage
errors return exit code 2.

See [Route inspection](route-inspection.md) for the complete `routes list`
table and JSON contract. It is a source-only command: it builds the canonical
route graph and URL-helper projection but does not require, read, compare, or
write `app/_pyganini`. Its enriched `pyganini.routes.v1` payload reports static
metadata, navigation and destination edges, implementation bindings, mounted
selection, and root error-render facts. `routes layouts` is also source-only,
but does not build or validate the URL-helper projection.

`routes explain` is source-only as well, but takes one target and uses the
graph's dispatch-equivalent path matching. A match includes declaration,
implementation, and root error-render sections; it does not validate URL
helpers.

`routes render-units` is source-only and reports declared template capability
for live page, fragment, and action endpoints. It does not load Jinja or
observe handler results; see [Render-unit inspection](route-inspection.md#render-unit-inspection)
for its fields and `pyganini.render_units.v1` schema.

## Render-unit inspection

`pyganini routes render-units` and `python -m pyganini routes render-units` use the
same source-only root selection and one canonical `RouteGraph`:

```text
pyganini routes render-units [--app-root PATH] [--json]
```

The command emits one row for each template-backed page, fragment, or action
endpoint returned by `iter_endpoints()`. It reports the final route, exact
methods, retained Jinja environment name and source, route source, live
owner, selected mount evidence, and layout mode. Pages report their complete
outer-to-inner effective layout chain. Fragments report `layout_mode=none`
and an empty chain. Actions report `layout_mode=page-result`; that chain is
used only when the action returns `Page`. A direct Starlette `Response` is not
inferred from this static declaration.

The default output is a deterministic ASCII table beginning with:

```text
KIND  METHOD  ROUTE  TEMPLATE  TEMPLATE_SOURCE  SOURCE  OWNER  MOUNT  SOURCE_PATH  LAYOUT_MODE  EFFECTIVE_LAYOUTS
```

`--json` writes a two-space-indented, ASCII-escaped `pyganini.render_units.v1`
object with `schema` and `render_units` keys. Empty results are successful and
retain the complete header or empty array. Layouts are supporting evidence,
not independent rows. Unselected mounted declarations and template-less
direct-response endpoints do not appear.

Argument errors, including unknown, abbreviated, misplaced, or positional
arguments, return `2` before root selection. Root, project, and graph failures
retain their existing diagnostics and return `1`. Reachable projection,
encoding, and stdout failures return `1` with:

```text
pyganini routes render-units: PYGANINI017 route-inspection: <message>
```

The command does not read or write `app/_pyganini`, import or execute application
code, load or parse Jinja, render templates, inspect includes or inheritance,
validate URL helpers, or participate in `pyganini check` or `pyganini generate`.

## Routes refs

`pyganini routes refs` and `python -m pyganini routes refs` inventory direct HTMX
request attributes in Jinja source:

```text
pyganini routes refs [--app-root PATH] [--json]
```

The only recognized attributes are `hx-get`, `hx-post`, `hx-put`, `hx-patch`,
`hx-delete`, and their `data-hx-*` equivalents. The scanner derives roots from
template evidence in the canonical graph: `app/routes`, selected
`app/mounts/<identity>` trees, and explicit shared route-kit template roots.
Nested roots are collapsed and files are scanned once in app-relative POSIX
order. Every regular file with the exact `.jinja` suffix below a selected root
is inspected, including an unreferenced file. Files outside those roots do not
contribute rows.

The command masks standard Jinja delimiters with `Environment.lex()`, parses
only an isolated attribute expression with `Environment.parse()`, and uses
Python's standard-library `HTMLParser` for start tags and attributes. It does
not render, import the application, follow includes or inheritance, evaluate
expressions, or inspect `href`, form actions, inherited HTMX attributes, or
custom Jinja delimiters. Source positions report the start-tag line and fixed
column `1`.

Rows have one of these statuses:

- `resolved`: exact method and literal path or canonical generated `urls...path`
  helper shape identifies one endpoint;
- `unmatched`: a literal path has no exact endpoint for the request method,
  including an unknown path; a helper shape is canonical but exists only for
  another method;
- `dynamic`: the value or helper shape is application-owned or unsupported;
- `external`: the value is a hierarchical or protocol-relative external URL;
- `invalid`: the value is empty, relative, malformed, or has invalid helper
  arguments.

The text form is deterministic and begins with:

```text
STATUS  METHOD  ROUTE  KIND  ATTRIBUTE  SOURCE  VALUE
```

The default form prints one complete ASCII table. `--json` prints one
`pyganini.refs.v1` object with `schema` and `references` keys, two-space
indentation, ASCII escaping, and one final newline. Both forms use the same
ordered rows and retain duplicate attributes.

Argument errors, including unknown, abbreviated, misplaced, or value-bearing
options, return `2` before project selection. Existing root, project, graph,
and `PYGANINI016 url-interface` failures retain their diagnostics and return `1`.
Scanning, lexical masking, HTML parser, unexpected resolution coordination,
encoding, and stdout failures use:

```text
pyganini routes refs: PYGANINI017 route-inspection: <message>
```

Unmatched, dynamic, external, and invalid rows are successful inventory
results and return `0`. Unsupported or syntactically unparseable isolated
attribute expressions are `dynamic` and return `0`; only unexpected isolated
parser-coordination failures use `PYGANINI017`. The command writes no files and
does not change
`pyganini check`, generation, dispatch, rendering, or request behavior.

## Root selection

When `--app-root` is present, Pyganini resolves that exact directory, requires its
`pyproject.toml` marker, and does not search upward. Otherwise it resolves the
current working directory and searches each physical parent through the
filesystem anchor. The nearest valid `[tool.pyganini]` marker wins.

Run from the application root or any nested directory. Editor tasks and tests
whose working directories are outside the application pass `--app-root`.

After selection, Pyganini requires real, non-symlinked `app` and `app/routes`
packages and their `__init__.py` files. Both commands then scan and validate
the complete route tree and every referenced source tree below optional
`app/mounts`. Unreferenced mount children are ignored. Declared endpoint
templates and every fixed
`layout.jinja` must be contained regular UTF-8 files. Jinja source is not parsed
during generation. A route or template failure stops before generated-state
comparison, staging, replacement, or cleanup.

## Generate

`pyganini generate` validates the route graph and complete expected plan before
writing. It
initializes an absent or empty `app/_pyganini`, writes changed files through
same-directory temporary files, flushes and synchronizes them, replaces each
destination atomically, preserves identical file mtimes, and then removes
obsolete owned output without following symlinks. Generated operations remain
anchored to the verified generated-directory identity if a pathname is changed
concurrently. Expected files must be regular files.

Success prints:

```text
Pyganini generated state: written=<n> unchanged=<n> removed=<n>.
```

The current first generation writes four files: the ownership marker, the
generated package bootstrap, `asgi.py`, and `urls.py`. The generated dispatch
module exposes typed `create_router` and `router` and contains deterministic
route, template, layout, owner, and selected-source facts for controlled
runtime imports, dispatch, and rendering. The URL module exposes typed `urls`
and `mount_urls` values: `urls` has the live route-shaped paths, while
`mount_urls` binds selection-filtered source helpers to a live owner. Both
support explicit base-path rebinding.

## Check

`pyganini check` builds the same route graph, then computes and validates the same
expected bytes. It reports
missing, stale, obsolete, or ownership-conflicting state without creating,
replacing, deleting, or touching application entries. Success prints:

```text
Pyganini generated state is current.
```

## Assets

When an application contains `assets/build`, the asset command group manages
the separate fingerprinted product boundary:

```text
pyganini assets dist [--app-root PATH]
pyganini assets check [--app-root PATH]
pyganini assets list [--app-root PATH] [--json]
pyganini assets clean [--app-root PATH]
```

`dist` writes changed `assets/dist` files, `assets/pyganini_assets_gen.py`, and
`assets/.pyganini/assets.json`, then removes only stale files recorded by valid
prior state. `check` is read-only. `list` computes its table or
`pyganini.assets.v1` JSON from `assets/build` without reading managed output.
`clean` removes stale recorded files and updates state without rebuilding
current output. See [Assets](assets.md) for the fixed layout and application
host boundary.

Normal `generate` and `check` coordinate this asset state after route state
when `assets/build` is enabled. Asset products never enter the `app/_pyganini`
route plan. Without a build tree or managed indicators, normal command output
and the four route-generated products remain unchanged.

Asset diagnostics use `PYGANINI020 asset-filesystem` for invalid boundaries,
inputs, and state, `PYGANINI021 asset-state` for reachable check differences,
and `PYGANINI022 asset-write` for staging, replacement, cleanup, and partial
mutation failures. Asset command usage errors return `2`; expected asset
failures return `1` and do not print a traceback.

## Diagnostics and exit codes

Diagnostics go to stderr in this form:

```text
<path-or-pyganini>: <code> <phase>: <message>
```

Expected project and generated-state failures return exit code 1 and do not
print a Python traceback. Codes `PYGANINI001` through `PYGANINI004` cover root,
configuration, and project layout. `PYGANINI005` and `PYGANINI006` cover stale state
and ownership. `PYGANINI007` covers pre-mutation plan or staging failures; private
staging files are cleaned when those failures occur.
`PYGANINI008` reports completed mutations after a later failure and instructs the
developer to rerun `pyganini generate` followed by `pyganini check`.

Route-source failures use these codes:

- `PYGANINI009 route-filesystem` reports an invalid route directory, package
  marker, convention file, required template, symlink, containment boundary,
  or source read.
- `PYGANINI010 route-declaration` reports invalid Python syntax or a declaration
  that the static parser cannot normalize.
- `PYGANINI011 route-collision` reports dynamic sibling, repeated parameter,
  normalized local path, or exact method-and-path ownership conflicts.

The command prints all reachable route diagnostics in stable structured order:
diagnostic family, live owner, mount identity, mounted source path, final path,
method, then source position. Ordinary diagnostics use their own source path
for the owner and source positions. The command returns exit code 1. Neither
command imports route, handler, layout, or application modules while building
the graph or generated plan. Controlled application imports occur later, when
the host imports
`app._pyganini.asgi`. Import-time dispatch failures use private diagnostics
`PYGANINI012 route-import` and `PYGANINI013 route-callable`; invalid handler results
use `PYGANINI014 route-response` at request time. Generated-router environment
failures use `PYGANINI015 render-configuration`; Jinja load and render failures use
`PYGANINI015 render-template`. Template loading and rendering occur only after a
handler returns a Pyganini render value.

`pyganini routes list` preserves the root, configuration, project-layout, graph,
and generated URL-helper diagnostics and adds `PYGANINI017 route-inspection` for
a reachable inventory or complete-output encoding failure. The latter uses:

```text
pyganini routes list: PYGANINI017 route-inspection: <message>
```

Expected route-list failures return 1, write no inventory payload, and print no
traceback. Invalid `--mount` syntax is an argparse usage failure and returns 2
before root selection; a valid unknown mount returns a successful result with
no route rows and the global error-render facts.

## Routes layouts

`pyganini routes layouts` accepts only the command and optional exact
`--app-root PATH` form. It selects source-owned project paths, builds one
static `RouteGraph`, derives accepted inventory occurrences, selects page and
action layout chains through the same private graph helper used by generated
dispatch, and writes one complete ASCII tree. It does not require or inspect
`app/_pyganini`, validate URL helpers, import application or generated modules,
execute handlers, load Jinja, or write files.

The output starts with `LAYOUT MAP` and `/`, uses `|-- ` and `` `-- ``
connectors, and places every layout, page, fragment, action, and final path at
its application-relative live URL. Layout entries show `source`, `owner`,
`mount`, and `source_path`. Endpoint entries show the same evidence plus
`layouts=[...]`; fragments append `(not wrapped)` and actions append
`(valid Page results only)`. Pages and actions use the selected outer-to-inner
source-position chain. The footer records that declared-template `Page`
results use the chain, fragments do not, and direct Starlette `Response`
results bypass templates and layouts.

The tree is deterministic, static paths precede dynamic paths, output is
ASCII without ANSI styling, and the complete payload is prepared before the
single stdout write. Project and graph failures retain their existing
diagnostics. Projection, reconciliation, encoding, and stdout failures use:

```text
pyganini routes layouts: PYGANINI017 route-inspection: <message>
```

Expected failures return 1 with no partial map or traceback. Unsupported
options, positional arguments, and abbreviated options are argparse usage
errors with exit code 2.

## Routes explain

`pyganini routes explain` accepts exactly one target and the optional `--app-root`
and `--method` options. Long-option abbreviation is disabled. The method
defaults to `GET`; explicit methods are trimmed, validated as ASCII HTTP tokens,
and uppercased. Target and method validation occur before project-root
selection, and malformed input returns argparse exit code 2.

The target is either an absolute path beginning with `/` or a hierarchical
absolute URL with an ASCII scheme, `://`, and a valid non-empty authority. A
leading `//` in a path is literal. Query and fragment text is ignored, while
encoded `%3F` and `%23` remain path data. The extracted path is percent-escape
validated and decoded exactly once as strict UTF-8 to the ASGI matching path.
No slash, dot-segment, case, Unicode, or trailing-slash normalization occurs.

For a match, the command writes one complete ASCII explanation to stdout:

```text
ROUTE EXPLAIN
url_path="/users/a%252Fb"
asgi_path="/users/a%2Fb"
method=GET
status=matched

MATCH
kind=page
methods=GET,HEAD
route=/users/{id}
dispatch_method=GET
params=[id="a%2Fb"]
handler=<module.symbol>
source=<app-relative path:line:column>
owner=-
mount=-
source_path=-
layouts=[<outer-to-inner positions>]

DECLARATION
<static metadata, navigation, destination, and mount evidence>

IMPLEMENTATION
<handler binding, declaration, template, and request-data evidence>

ERROR_RENDER
<root templates and selected page-layout evidence>

RULES
  Page results with a declared endpoint template use the displayed layout chain.
  Fragment results are not layout-wrapped.
  Direct Response results bypass templates and layouts.
  HEAD selects the GET handler and suppresses response body payloads.
  Route declaration metadata is static, display-only, and does not affect matching or runtime policy.
  Excluded mounted candidates are inspection evidence and are never live endpoints.
  Error Page results use the listed root template and selected page layouts.
  Error FragmentResponse results use the listed root fragment template without layouts.
```

The live endpoint, handler, source, mounted owner/source path, parameters, and
layout positions replace the placeholders. `HEAD` reports `method=HEAD` and
`dispatch_method=GET` without executing the handler. Fragments report
`layouts=[] (not wrapped)` and actions append `(valid Page results only)`.
Path ownership follows generated dispatch: the first matching static or
dynamic path owns the result before method selection, so an earlier static
path can produce 405 instead of falling through to a later dynamic path.

A path miss returns 1 and writes no stdout:

```text
pyganini routes explain: PYGANINI017 route-inspection: method=GET url_path="/missing" asgi_path="/missing" status=404 no route matches path error_page=<template-or-> error_fragment=<template-or-> root_layouts=[<root-layout-evidence>]
```

A matched path with an unsupported method returns 1 and reports the exact
canonical allowed set:

```text
pyganini routes explain: PYGANINI017 route-inspection: method=POST url_path="/users/new" asgi_path="/users/new" status=405 route=/users/new method not allowed; allowed=GET,HEAD error_page=<template-or-> error_fragment=<template-or-> root_layouts=[<root-layout-evidence>]
```

Project and graph failures retain their existing diagnostics. Reachable
matching, projection, encoding, and stdout failures use the
`pyganini routes explain: PYGANINI017 route-inspection: <message>` boundary, return
1, write no partial output, and print no traceback. The command does not read
or inspect `app/_pyganini`, import application modules, load Jinja, construct a
Request or Router, execute handlers, or write files.
