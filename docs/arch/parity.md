# Goldr parity and Pyganini qualification

Pyganini compares application capabilities and ownership with Goldr. Python,
ASGI, Starlette, Jinja, packaging, and typing require different mechanisms.
Mechanism differences do not establish a parity gap when developers can build
the same application workflow under the accepted ownership boundary.

The current Goldr baseline is `eb8ed60a34922cca988f81f2990ced85e72a81c3`.
Refresh that source comparison before changing a disposition or making a new
comparison claim. The checkout is not a Pyganini dependency.

## Capability ledger

`preserve` keeps the application capability and ownership. `adapt` keeps the
capability through Python-native mechanisms. `defer` retains a concrete open
question. `reject` records a boundary Pyganini will not own.

| Capability | Goldr behavior | Pyganini behavior | Disposition | Evidence owner | Limitation | Next owner |
| --- | --- | --- | --- | --- | --- | --- |
| Project selection, generation, and stale checks | Explicit application root, generated products, and non-writing check | `[tool.pyganini]`, `pyganini generate`, and `pyganini check` own one deterministic generated package | `adapt` | [Project and package generation](project-package-generation.md) | Several changed products use an honest per-file atomic boundary | Qualification and packaging remediation when evidence changes |
| Coding-agent application support | Self-contained Goldr App skill, Codex installation, Claude plugin marketplace, and application rules | Self-contained Pyganini App skill adapts application workflows to Python/Jinja/ASGI with the same distribution capabilities | `adapt` | [Pyganini App skill](../skills/pyganini-app/SKILL.md), [Coding agents](../user/coding-agents.md) | Local package and documented-app validation does not establish hosted installation | Update affected skill references with public-contract changes; hosted installation after publication |
| Filesystem routes and declarations | Static route tree with explicit pages, fragments, and actions | One AST-derived `RouteGraph` from `app/routes` and direct `Route = route(...)` declarations | `adapt` | [Route graph](route-graph.md) | Dynamic values containing decoded `/` remain unsupported | Route-graph child after a concrete Starlette-compatible use case |
| Generated dispatch | Generated HTTP dispatch consumes the route graph | Generated public Starlette `Router` values consume the same graph | `adapt` | [Generated ASGI dispatch](generated-asgi-dispatch.md) | FastAPI dependencies and OpenAPI do not define Pyganini routes | None; host integration remains application-owned |
| Pages, layouts, fragments, actions, and direct responses | templ components and generated layout composition | Sync Jinja rendering, explicit `Page` and `FragmentResponse`, and public Starlette responses | `adapt` | [Rendering and responses](rendering-responses.md) | Jinja does not provide templ-equivalent compile-time HTML checks | Typed layout keys remain deferred |
| Generated URL interfaces | Generated route-shaped URL helpers | Generated typed Python namespaces, dynamic binders, and `.path` values | `adapt` | [Generated URL interfaces](generated-url-interfaces.md) | Decoded slash values do not round trip through Starlette dispatch | Route and URL child after a supported matcher design exists |
| HTMX forms and request data | Visible HTMX markup with route responses and parsed forms | Visible Jinja `hx-*`, direct Starlette forms, and bounded immutable captured request data for sync or async actions | `adapt` | [HTMX and forms](htmx-async-forms.md) | Applications own validation, uploads, and response policy | Application code unless another shared wire need appears |
| Shared route implementations | Kit routes share handlers and templates across owners | `route_kit` keeps shared Jinja and handlers explicit | `adapt` | [Route kits](route-kits.md) | Shared code receives no framework dependency container | None |
| Mounted route subtrees | Live owners select reusable filesystem route sources | `route_mount` selects `app/mounts` source with generated binding | `preserve` | [Mounted routes](mounted-routes.md) | Live owners retain middleware, auth, and state policy | None |
| Route inspection | Commands expose declaration metadata, mounted selection, route, layout, reference, and render evidence | Source-only list, layouts, explain, refs, and render-units commands consume `RouteGraph`; list and explain report Python handler and root error-render evidence | `adapt` | [Route inspection](route-inspection.md) | Inspection does not import handlers or render Jinja | New inspection child only for graph-backed application evidence |
| Navigation | Generated routes provide explicit trail and destination data with a handler base path | Generated destinations plus request-scoped `nav(request)` values use effective ASGI `root_path` | `adapt` | [Navigation](navigation.md) | Pyganini does not own proxy-header policy, browser history, or session return stacks | Application host and code |
| Live route middleware | Live route policy composes with generated dispatch | Live `middleware.py` composes application-owned Starlette middleware inside selected generated routes | `adapt` | [Application composition](application-composition.md) | Host, static, and lifespan stay outside route middleware; configured page-source misses select static live ancestry | Application host |
| Layout-aware generated error presentation | Custom error components use generated layout composition | One optional `RouteErrorHandler` returns existing render values; static root templates use root or selected live layout evidence and appear in source inspection | `adapt` | [Generated ASGI dispatch](generated-asgi-dispatch.md) | Host routes, static files, lifespan, post-start failures, and content policy stay application-owned | Application code for error content policy |
| Development loop | Goldr integrates generation, templ work, proxying, and browser reload | Two explicit example wrappers share app-owned supervision and refresh-only content/Jinja watching | `adapt` | [Development workflow](../user/development.md) | Production hosts stay opt-out; native Windows supervision is absent | Application tooling; Windows qualification remains deferred |
| CSRF wire helpers | Optional guard, middleware, token validation, and helpers | `pyganini.csrf` supplies a Python guard and ASGI middleware; Jinja keeps markup visible | `adapt` | [CSRF](csrf.md) | Applications own secrets, failure policy, and middleware placement | Application code |
| SSE wire helpers | Typed events, comments, IDs, and retry fields | `pyganini.sse` encodes wire frames for application-owned `StreamingResponse` | `adapt` | [SSE](sse.md) | Pyganini owns no subscriber, replay, flush, or stream lifecycle | Application code |
| Named SSE browser events | Optional named-event swap helper and fixed helper serving | `pyganini.browser` provides one stable HTMX 4 hook and an explicitly mounted fixed-resource app | `adapt` | [Browser helpers](browser.md) | Applications own stream production, URLs, mounting, CSP, cache policy, and deployment | Application host and templates |
| Runtime template inspection | Generated render boundaries and an optional development overlay | Typed router modes emit deterministic Jinja render markers; the shared browser app serves an application-enabled overlay helper | `adapt` | [Template inspection](../user/template-inspection.md) | Static inspection remains source-only; direct responses and application policy stay outside instrumentation | Application development configuration and host |
| Fingerprinted assets | Final build input projects to SHA-256-named browser assets | `pyganini assets` projects `assets/build` and generates typed lookup metadata | `adapt` | [Assets](assets.md) | Applications own compilation, static serving, cache policy, and deployment | Application asset pipeline |
| Bounded React and Svelte islands | Route-local islands integrate with HTMX lifecycle | Independent examples own Vite, mount and teardown, JSON calls, and state | `preserve` | [Client islands](../user/client-islands.md) | Pyganini provides no shared island API, hydration, or client router | Application frontend |

| Trusted content pages | First-party HTML/Markdown bodies and strict metadata outside route sources | Optional `pyganini[content]` reads trusted ordinary `Path` roots on each GET/HEAD; packaged resources use app-owned extraction lifetime | `adapt` | [Content](content.md) | No untrusted uploads, hostile mutable filesystem confinement, root index, cache, assets, or renderer-owned I/O | Application content policy |
| Additional page source | Optional callback after an ordinary generated-router miss | Typed sync/async `AdditionalPageSource` returns trusted `AdditionalPage`, a response, or decline; static source-only layouts/middleware project from the same graph | `adapt` | [Generated ASGI dispatch](generated-asgi-dispatch.md) | Matched routes and 405 remain terminal; dynamic and mounted-source ancestry do not invent content ownership | Application source callback |
| GFM and heading IDs | Goldmark GFM and heading anchors | Optional Markdown parser supports tables, task lists, strikethrough, autolinks, raw HTML, and per-render heading IDs | `adapt` | [Content pages](../user/content-pages.md) | Python parser syntax/slug details are documented adaptations; rendered bodies are trusted unsanitized HTML | Application authors |
| Stable HTMX status/CSRF behavior | HTMX 4.0.0, inherited headers, visible element status rules | Matching pinned local core/SSE assets; stable hook/event names; inherited CSRF and explicit 422/4xx/5xx rules in Jinja | `preserve` | [HTMX](../user/htmx.md), [Browser helpers](browser.md) | Framework owns no global swap or CSRF policy | Application templates |

## Comparative workflows

Route addition and refactoring run through the explicit route graph, public
`generate`/`check` commands, generated Python, both type checkers, source
inspection, and ASGI requests. Goldr uses Go/templ generation and compilation.
Pyganini preserves the explicit checked workflow without startup discovery.
Q030/Q031 cover static-page addition and dynamic-parameter rename through an
installed wheel.

Invalid declarations fail before generated mutation. Q040/Q041 cover collisions
and unsupported expressions. Q042 requires a missing declared template to fail
source commands with `PYGANINI009 route-filesystem`, no handler import or route
JSON, and unchanged products. Q043 proves source-only inspection stays
import-free while generated startup retains `PYGANINI012 route-import` and its
application cause. Q044 owns request-time propagation and response-start safety.

External content additions and edits need no route generation. Declared routes
retain precedence. A configured source selects layouts and middleware from
static live nodes, including nodes with no endpoint, and preserves host prefixes.
Content bodies never become Jinja source, route inventory, or generated URLs.
`AdditionalPage` adapts Goldr's concrete page component to finished trusted HTML
and explicit Python mappings; the governing content child records the naming
and response-contract mapping.

Development saves use app-owned repository tooling in two consumers. Content
and existing Jinja changes publish a revision without generator commands,
process signals, changed route-product bytes/mtime, or a new PID. Python/final
asset changes retain generate/check before replacement. The opt-in development
host uses a read-only same-origin SSE stream and native EventSource, with
invalid-save recovery and reconnect comparison. A framework proxy, templ
compiler, Go watcher, and installed generic dev command are not required for
this workflow.

## Application-owned boundaries

The application owns ASGI hosting, middleware policy, authentication, sessions,
persistence, dependencies, validation, static serving, cache policy, logging,
deployment, and release. FastAPI remains a tested host integration; its
handlers, dependency model, and OpenAPI do not define Pyganini routes.
Jinja remains synchronous and is the only built-in renderer.

Pyganini rejects SPA routing, hydration, client-state ownership, an island
registry, generated JavaScript, a framework DI container, and a framework-owned
development server/proxy. Applications may own bounded client islands and
complete build/lifecycle bridges. Go toolchain modernization and module layout
changes do not establish Python feature gaps.

## Open deferrals

| Deferral | Current boundary | Promotion evidence | Next owner |
| --- | --- | --- | --- |
| Native Windows supervision | Example process groups target macOS and Linux | A Windows application supplies bounded process-tree and signal evidence | Platform qualification child |
| Decoded `/` in dynamic values | Starlette dispatch uses decoded paths | A matcher design proves generation and dispatch agreement without another route model | Route and URL child |
| Typed layout-data keys | Immutable string-keyed mappings | Multiple layouts establish a stable shared typed key contract | Rendering child |
| Performance claims | No comparative speed claim | Accepted methodology controls environment, workload, and thresholds | Performance qualification child |

## Qualification ownership

Root pytest covers public behavior, typing consumers, generated output, and
installation from both wheels and sdist-derived wheels on Python 3.13/3.14.
The plain package does not eagerly import Markdown dependencies; the optional
extra has separate distribution and resource-lifetime checks. Example browser
proof uses local HTMX 4.0.0 assets and same-origin requests. Both client islands
retain mount, teardown, pending-operation cleanup, and remount behavior.

The standalone qualification tool owns candidate identity, the fifteen Q001-
Q080 scenarios, installed-distribution/host workflows, checksums, and process
cleanup. Q010 uses all extras and adds focused content consumer typing alongside
CSRF, SSE, and generated assets. Its external report is the authority for its
candidate-specific verdict; a prior passing report does not qualify changed
source. Implementation-owner acceptance, performance, commit, publication,
remote push, and release are separate gates.
