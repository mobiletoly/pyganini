# Content and Additional Page Sources

Additional pages are a miss branch of generated dispatch. `_dispatch_generation`
projects static prefix plans from the same validated `RouteGraph` used for
endpoints, helpers, checks, and inspection. There is no content scan during
route generation and no content route identity.

## Dependency direction

`AdditionalPage` belongs to `_render`, and `AdditionalPageSource` belongs to
`_dispatch`; the root package exports both. Existing route and error response
aliases exclude `AdditionalPage`. `pyganini.content` imports those render values,
the pure graph-local path helper, and optional Markdown dependencies. Core
bootstrap and generated modules do not import the content package.

`content.Config` holds a trusted `Path`; `new` checks once and creates a live
`Pages.resolve` callable. `check` and per-request reads share file validation.
All errors use source-relative `ContentError.path` and `rule` evidence with
retained causes. The package owns neither Jinja nor generated application code.

## Generated miss plans

Only original live nodes below `app/routes` without dynamic ancestry contribute.
Each plan carries a static prefix, cumulative layout and middleware evidence,
and layout inspection markers. Declaration-free nodes are included. Mounted
source nodes are excluded; the live owner's own static ancestry remains live.
Selection matches whole segments of original graph-local path evidence once.
Scope mutations inside middleware do not select a different plan.

Endpoint-used middleware is captured during the existing controlled startup
imports. Source-only markers are loaded only when a source is configured.
Each router constructs fresh public Starlette middleware instances. Nil-source
routers do not load source-only bindings or add their layout names to runtime
autoescape checks; static generation/check still validates declared sources.

Static, dynamic, and mounted matches retain path-before-method priority. Method
mismatches, endpoint failures, explicit matched-path rejections, and non-HTTP
scopes never call the source. The source-aware router's default miss application
runs the selected middleware around resolution, rendering, writing, and final
404. It adds no endpoint, inventory row, URL value, navigation state, or parameter.

## Response and error boundaries

Sync sources are offloaded with the current AnyIO cancellation contract. Async
sources and returned awaitables are awaited on the existing loop. Resolution
and Markdown conversion finish before synchronous Jinja layout work begins.
`AdditionalPage` enters the existing shared layout loop without a page-template
stage. Its body is marked safe privately; metadata/layout strings stay escaped.
Rendering is buffered before response start. Direct Starlette responses bypass
layouts, retain streaming/background behavior, and share HEAD suppression.

Source failures and declined 404 presentation occur inside selected middleware.
Middleware-origin exceptions use the outer generated boundary. Root error page
presentation uses only live root layouts; fragments remain layout-free. A
handled non-HTTP exception sends 500 and re-raises; post-start exceptions and
callback failures do not recurse. `PYGANINI023 additional-page-source` owns
source callable and return-contract failures; rendering, middleware, and error
callback diagnostics retain their existing owners. Error-callback diagnostics
receive the original decoded graph-local path captured before middleware;
generated filenames remain separate source evidence. Request bookkeeping
restores pre-existing host scope values on exit.

Inspection wraps only actual layouts. Authored content is not a fake declared
page, component, fragment, or generated render unit.

## Filesystem and parser ownership

Startup validation walks the complete tree lexically. Request validation reads
only traversed directories and the requested entry. File-kind checks reject
links/reparse/special entries, recognized sources are checked again after open,
and reads are bounded to limit plus one bytes. There is no stat-only size trust,
cache, snapshot, last-known-good result, or transactional multi-file update.
The configured root and descendants are checked without rejecting OS aliases
above it. This remains trusted deployment storage, not hostile-writer confinement.

`_request_path.local_path` uses trusted decoded `root_path` and original public
ASGI path evidence. It compares optional raw evidence after strict UTF-8 percent
decoding and maps the decoded host-prefix byte boundary to its unchanged raw
suffix. Escaped separators within the host prefix do not consume local path
segments. Custom sources use this prefix projection without the content
package's narrower identifier grammar.

A request-local MarkdownIt `gfm-like` parser enables raw HTML, task lists, and
anchors. A private public-method override accepts trusted destination protocols.
Parser state and duplicate heading counters are never shared between requests.
The optional dependency boundary and exact byte limits are documented in
[Content pages](../user/content-pages.md). Importing content checks the parser,
plugins, and linkifier together and reports missing dependencies as an
actionable `ImportError`. Package-resource directories and
lifetimes are application-owned standard-library composition.
