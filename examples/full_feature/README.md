# Pyganini Full-Feature Example

This is a runnable downstream contact-directory application. It keeps the
route tree, Jinja templates, generated URL values, fingerprinted browser assets,
visible HTMX attributes, and application ownership boundaries in one small
product scenario.

## Run it

From this directory, install the committed example lock:

```text
uv sync --locked --all-groups --python 3.14
```

For the ordinary application-owned Uvicorn server:

```text
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Use Uvicorn's ordinary
`--port` option to select another local port. Pyganini core does not own the
server command.

### Application development loop

The example also owns a fixed development loop for macOS and Linux:

```text
uv run --locked --python 3.14 python dev.py [--host HOST] [--port PORT]
```

The defaults are `127.0.0.1` and `8000`. The command derives this example's
root from `dev.py`, runs `pyganini generate` followed by `pyganini check`, and only
then starts the fixed `app.main:app` Uvicorn process. It watches Python files
recursively under `app/` while excluding the exact `app/_pyganini/` generated
tree, plus every non-directory change below `assets/build`. It ignores
`assets/dist`, `assets/.pyganini`, and the generated asset module. One coalesced
Python or asset change set causes one generation/check preparation and, when
successful, one server replacement. A Python or asset edit restarts the server
even when generation writes no bytes. Before preparation it prints the resolved
application root, server URL, both watch scopes, generated/output exclusions,
and the manual-refresh policy; it prints these lines even when preparation
fails.

Generation and check run while a working server remains alive. If either
fails, the current server is retained and the loop waits for another Python
edit. If Uvicorn exits, the loop reports the exit once, reaps it, and waits for
the next Python edit; it does not retry on a timer. Ctrl-C and SIGTERM stop and
reap the server process group with graceful signal escalation.

Jinja template content is not watched. The default Jinja environment checks
template changes at request time, so refresh the browser manually to see
template changes. Template content does not require `pyganini generate`; a
template name or route declaration change is Python and does trigger
generation. Deleting or renaming a template without updating Python may fail
on the next request and is not proactively validated. The loop does not
provide browser reload, proxying, asset building, deployment policy, Windows
supervision, or arbitrary commands. Pyganini core owns no server or reload
command.

## Product routes

The application host also owns one finite streaming proof route outside the
generated route tree:

- `/events` is an application-owned Starlette `Route` that uses
  `pyganini.sse` with a normal `StreamingResponse`. It emits one comment and one
  ignored named event followed by one selected `contact` event, then finishes;
  the `Last-Event-ID` value is shown in the selected event data. The host also
  mounts `pyganini.browser.create_app()` explicitly at `/pyganini`, while the root
  Jinja template loads the local HTMX SSE extension and helper and keeps the
  connection, event selector, and swap behavior visible.
  The test proves framing, response media type, cache policy, and host
  composition only. It does not prove production flushing, proxy behavior,
  subscriber management, reconnect replay, or long-lived resource cleanup.

The contact-directory route tree owns these surfaces:

- `/` introduces the application and links to generated routes.
- `/settings` demonstrates a static page and active navigation.
- `/users` mounts the contact-directory source with `/`, `/table`, `/create`,
  and `/{id}` selected. It renders the form and directory table, including
  typed navigation destination links.
- `/users/table` is a GET table fragment with a status filter.
- `/users/create` is a POST action supporting HTMX and ordinary HTML fallback.
- `/users/{id}` is a dynamic contact detail page.
- `/settings/users` mounts the same source with only `/` selected. Its owner
  supplies active contacts, a settings title and layout, and a read-only
  policy. The selected root declaration still includes its `/table` fragment,
  while the source `/create` action and `/{id}` page are excluded.
- Both owners bind `mount_urls.contact_directory` to their own generated live
  URL value. The source keeps its mounted inner layout while each live owner
  supplies its outer layout, data, policy, and request-scoped creator.
- Each live owner also supplies an application-owned `middleware.py` marker.
  The users and settings owners expose distinct route policy state over the
  same reusable source; `app/mounts/contact_directory` owns no middleware.
- Navigation is application-owned HTML. The users owner overrides the mounted
  source's `Directory` default with `Contacts`, resolves contact labels from
  repository data, and declares the `from-contacts` destination key. Detail
  links carry a bounded local return target; the detail page selects an
  explicit alternate trail and renders semantic Back markup.
- `/problem` raises a generated-route exception presented by the
  application-owned `RouteErrorHandler` as a layout-aware `Page` with status
  500. The live root statically declares `error_page.jinja` and
  `error_fragment.jinja`. The same callback presents generated 404, 405, 413,
  415, and matched 418 outcomes, returns a layout-free fragment for explicit
  HTMX requests, preserves `Allow` and HEAD response semantics, and
  demonstrates direct-response and `None` delegation branches selected by an
  application header. `X-Example-Route-Error: matched` makes the mounted
  `/users` handler raise the matched 418 used to prove root, live-owner, and
  mounted-source layout ancestry.

The application stores seed and created contacts in memory. It makes no
multi-process, transaction, persistence, account, authentication, or
authorization guarantee.

## Generation and checks

Generate Pyganini-owned files from the example root, then check them without
writing:

```text
uv run --locked --python 3.14 pyganini generate
uv run --locked --python 3.14 pyganini check
uv run --locked --python 3.14 pyganini assets dist
uv run --locked --python 3.14 pyganini assets check
uv run --locked --python 3.14 pyganini assets list --json
uv run --locked --python 3.14 pyganini routes list
uv run --locked --python 3.14 pyganini routes list --json
uv run --locked --python 3.14 pyganini routes list --mount contact_directory
uv run --locked --python 3.14 pyganini routes layouts
uv run --locked --python 3.14 pyganini routes explain /
uv run --locked --python 3.14 pyganini routes refs
uv run --locked --python 3.14 pyganini routes refs --json
uv run --locked --python 3.14 pyganini routes render-units
uv run --locked --python 3.14 pyganini routes render-units --json
uv run --locked --python 3.14 pyganini routes explain 'http://127.0.0.1:8000/users/42?view=profile#details'
uv run --locked --python 3.14 pyganini routes explain --method HEAD /users/42
uv run --locked --python 3.14 pyganini routes explain --method POST /users/create
uv run --locked --python 3.14 pyganini routes explain /users/table
```

The generated package under `app/_pyganini/` and the fingerprinted products under
`assets/dist`, `assets/.pyganini`, and `assets/pyganini_assets_gen.py` are committed
product surface created by the installed editable `pyganini` distribution resolved
through the example's local uv source. Do not edit generated files by hand.

Route modules use Pyganini's mounted-source vocabulary. The reusable handlers and
templates live under `app/mounts/contact_directory/` with creator-free
`route_kit(...)` declarations and colocated templates. The live owners use
`Route = route_mount(...)`, `mount_route(...)`, and `mount_urls` to select and
bind the source. The example's data and read/create policy are application-owned
and do not demonstrate framework authentication or authorization.

`routes list` reads the source route graph and reports ordinary and mounted
endpoint/layout rows without importing `app` or reading `app/_pyganini`. The root
route declares ordinary metadata, and the selected contact-directory roots
inherit metadata from their shared mounted source. The `pyganini.routes.v1`
payload also reports navigation, destinations, inbound trail keys,
implementation bindings, and root error-render facts. With
`--mount contact_directory`, selected rows are `included` for both owners and
the settings owner's `/create` and `/{id}` source candidates appear as
non-live `excluded` evidence.

`routes layouts` renders the same source graph as a final live-path ASCII tree.
It shows the ordinary `/users` and `/settings/users` layouts, the selected
`contact_directory` layout below both owners, complete outer-to-inner page and
action chains, and the `/table` fragments as not wrapped. The settings owner's
excluded `/create` action and `/{id}` page remain absent.

`routes explain` proves the installed source-only matcher for the ordinary root,
a full URL to the dynamic users page, HEAD selecting GET, the users create
action, and the unwrapped table fragment. It reports the final live owner,
mount, selected source path, declaration metadata, implementation binding,
destination evidence, root error templates, and outer-to-inner layouts for
both `/users` and `/settings/users`. The settings owner does not select the
source create or detail declarations, so `/settings/users/create` and
`/settings/users/42` return 404 rather than falling through to another owner.

`routes refs` inventories the direct HTMX request attributes in the selected
mounted Jinja source. Its graph-derived mount root includes the separately
included `directory.jinja`, and the four application-owned URL expressions are
reported honestly as `dynamic`. It does not read generated state or claim that
those application values resolve to routes.

`routes render-units` reports the selected template-backed pages, fragment, and
action without loading Jinja or importing the application. Its JSON schema is
`pyganini.render_units.v1`; the mounted rows retain their live owner, mount
identity, source path, and outer-to-inner layout evidence. The `/table`
fragments have `layout_mode=none`, while the create action has
`layout_mode=page-result` because only a `Page` result uses its displayed
chain. The direct-response-only `/problem` page and the settings owner's
excluded source declarations are absent. Root error templates are also absent
because the render-units schema remains endpoint-only. The list and explain
commands report those root error facts separately.

## Tests and typing

Run the focused HTTP and FastAPI host tests on both supported Python lines:

```text
uv run --locked --python 3.14 pytest -q tests/test_app.py tests/test_fastapi_host.py
uv run --locked --python 3.13 pytest -q tests/test_app.py tests/test_fastapi_host.py
```

Run example quality checks:

```text
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy app tests
uv run --locked --python 3.14 pyright app tests
```

The example's source and tests use strict mypy and Pyright settings. Generated
files remain Pyganini-owned; the example excludes them from Ruff formatting and
linting while mypy and Pyright consume the generated public interfaces.

## Browser proof

Install Chromium into the ignored example-local directory and run the local
server/browser proof:

```text
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked --python 3.14 playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked --python 3.14 pytest -q tests/test_browser.py
```

The test uses a pre-bound localhost socket, starts Uvicorn itself, rejects
browser requests to any origin other than that exact local server (including a
different localhost port), and closes the page, browser,
Playwright process, server, socket, and background task. It proves local CSS,
local HTMX, the bounded `422` swap policy, multipart creation and filename
display, fragment filtering, a dynamic detail link, and full-page generated
matched-error presentation with the root, users, and mounted source layouts at
1280px and 390px without horizontal overflow.

The ordinary module-level application leaves template inspection off. The
development loop starts `app.main:create_development_app --factory`; its
application-owned `PYGANINI_TEMPLATE_INSPECTION` value accepts `off`, `comments`,
or `overlay` and defaults to `overlay`. Overlay mode passes the typed router
mode, binds `/pyganini/pyganini-template-inspector.js` through the same decoded
`root_path` seam, and includes the script visibly in the root layout. The
browser proof covers the accessible controls, nested mounted-source markers,
HTMX replacement redraw, and mobile containment.

## HTML, HTMX, and application ownership

The form is ordinary multipart HTML first and visibly declares its generated
`action`, `hx-post`, `hx-target`, `hx-swap`, and `hx-encoding` values. A valid
ordinary POST returns a generated `303` redirect. A valid HTMX POST returns the
directory root with `HX-Retarget`, `HX-Reswap`, and `HX-Trigger`. Invalid fields
return visible `422` validation HTML without changing in-memory state. The
small local `app.js` policy permits that `422` HTML to swap while suppressing
other 4xx and 5xx response swaps.

The action opts into `capture_form(max_files=4, max_fields=16,
max_part_size=65_536, max_upload_size=65_536)`. Pyganini uses Starlette's public
multipart parser on the ASGI side, copies each upload into an immutable
`Upload`, closes parsed uploads, and only then runs the synchronous handler in
the worker thread. These values do not impose a total request-body limit;
Starlette may parse or spool input before the per-upload check. This is an
example policy, not a production upload security boundary.

The host application owns the typed dependency value on `app.state`, the
in-memory repository, the CSRF secret, middleware ordering, form parsing,
validation-before-mutation, forbidden response, host and live-owner middleware,
`nosniff` header, the `assets/dist` static mount, immutable asset cache policy,
Uvicorn launch, and error/status presentation.
It explicitly mounts `pyganini.csrf.TokenMiddleware` and uses `csrf.Guard` from
the public helper. `app/errors.py` owns the callback, result selection, page
and fragment content, layout data, direct and delegation policy, and optional
HTMX response headers. Pyganini selects root versus matched layout evidence from
the generated route boundary and restores required exception headers; it does
not infer content, format, classification, localization, or swap policy. The
HTTP and FastAPI tests use the explicit example header to prove the matched
mounted layout chain and HEAD body suppression without adding another route.
The isolated example uses an ephemeral 32-byte secret
and local non-secure cookies for HTTP development. A deployed HTTPS application
must supply stable secret material, enable secure cookies, and complete its own
threat review.

The create action requires exactly one textual `csrf_token` form value before
calling `Guard.validate()` and before repository mutation. Missing, duplicate,
or non-textual form evidence returns the same application-owned plain `403`.
The helper also rejects duplicate token headers or configured cookies without
selecting a first or last value.

The FastAPI test registers a separate API route and mounts a new generated
router with the same application-owned callback under `/directory`. FastAPI
retains API and OpenAPI ownership; the mounted Pyganini handlers receive the
host's application state, generated links include `/directory` once, and
host-owned fingerprinted asset URLs follow that same mount prefix.

The browser acceptance test also wraps the complete application in an
application-owned Starlette `/directory` mount. It proves prefixed breadcrumbs,
destinations, captured return state, semantic Back, assets, forms, HTMX, and
the named-event swap, ignored non-matching event, local helper requests, and
error presentation at desktop and 390px. It also opens a detail route without
an application-owned custom trail and clicks Home inside the canonical
breadcrumb, proving that canonical navigation cannot escape to host `/`. The
documented `app.main:app` launch command remains root-mounted.

## Local HTMX attribution

The application vendors `htmx.org` `4.0.0-beta6` core and `hx-sse` extension
from their versioned asset URLs under `assets/build/vendor`; Pyganini projects
both to fingerprinted `assets/dist` paths. The core SHA-256 is
`28fae7bbe8e8142b702debb9d5234a9a436d9435a4b5165b195aa1a7ed840d25`, and its
extension SHA-256 is
`d3aeb71073552b253eaee99badebd60607003b1c25ac567ab88187d6887ab522`. The
package metadata declares `BSD-0-Clause`. The complete Zero-Clause BSD notice,
package metadata URL, versioned license URL, asset URL, version, identifier,
hash, and SRI are recorded in `THIRD_PARTY_NOTICES.md`. The application makes
no browser-time request to a CDN and does not describe HTMX as MIT-licensed.

## Current limits

This example does not add or claim framework logging, authentication,
localization, JSON negotiation, built-in error templates, automatic CSRF
enforcement, upload storage, an asset compiler/build pipeline, a Pyganini
development server, database persistence, or production deployment policy.
Pyganini fingerprints final build files but does not compile, bundle, or optimize
them. Pyganini's optional CSRF helper does not own those application policies.
Those behaviors remain application-owned or outside this example's scope.
