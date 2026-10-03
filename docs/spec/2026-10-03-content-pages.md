# Spec: Content Pages and Additional Page Sources

Status: implemented
Created: 2026-10-03
Updated: 2026-10-03

## 1. Authority and Dependencies

This child belongs to the [Goldr parity umbrella](2026-10-03-goldr-parity-umbrella.md).
`AGENTS.md` and [Spec Authoring Policy](README.md) govern it. The owner accepted
this child on 2026-10-03 and authorized implementation within its scope. Commit,
push, publication, release, and deployment remain separate approvals.

The owner accepted the completed implementation on 2026-10-03 after independent
review, remediation confirmation, and corrected-candidate qualification.

The comparison target is Goldr `eb8ed60a34922cca988f81f2990ced85e72a81c3`.
Read its current `content/`, `docs/arch/content.md`, `docs/user/content-pages.md`,
and generator tests; older Goldr specs still mentioning `Fallback` are historical
and do not establish this contract. Pyganini planning head is
`8231ddd4537ef88b3a33dae3829ba584271aa283`.

Stable HTMX and automatic browser refresh belong to separate children. Neither
is required to prove the server-side content contract.

## 2. Goal

An application configures trusted content once at startup. On an ordinary
generated router miss, HTML or Markdown files can supply a complete page body
with metadata, wrapped in eligible static route-tree layouts and middleware.
External edits and newly added pages appear on the next request without route
generation or a server restart. Content pages never become generated routes.

## 3. Non-Goals

- CMS accounts, editors, drafts, publishing, collections, custom metadata,
  search, feeds, generated navigation, or content URL helpers.
- Untrusted uploads, sanitization, HTML parsing/repair, CSP, or a security sandbox
  for a filesystem writable by hostile concurrent actors.
- Remote storage, FS interfaces, plugins, source registries, chain helpers,
  caches, snapshots, watchers, or a second router/render tree.
- Catch-all declarations, new route filenames, renderer adapters, Jinja async,
  runtime route discovery, or FastAPI handler/DI models.
- Content commands in the framework CLI, automatic content discovery, a new
  starter generator, or framework-owned static file serving.
- Changes to declared route matching, URL binding, navigation identity, direct
  response behavior, middleware ownership, or error-hook semantics unrelated to
  the new miss branch.

## 4. Background and Evidence

`_route_graph.py` already records `RouteNode` values for directories without
`route.py`, with layout and middleware source evidence. `_dispatch_generation.py`
currently captures middleware only for endpoint consumers. Its `create_router`
has no source option. `_dispatch.py` distinguishes selected-route errors and
router not-found outcomes. `_render.py` renders a declared template, then wraps
its HTML through the selected synchronous Jinja layout chain in an AnyIO worker.

The umbrella records passing, isolated parser probes on Python 3.13 and 3.14.
They do not prove the proposed dispatch or filesystem implementation. No
Pyganini source or fixture has been changed during planning.

| Goldr concept | Proposed Python surface | Disposition and reason |
| --- | --- | --- |
| `HandlerOptions.AdditionalPageSource` | `create_router(additional_page_source=...)`, typed `AdditionalPageSource` | `adapt`: keyword argument and snake_case follow existing generated factories |
| `goldr.Page` with a self-rendering component | Existing route `Page`; source `AdditionalPage` with finished HTML | `adapt`: existing `Page.context` is state for a statically declared Jinja template; using it for raw source HTML would add competing route render conventions. `AdditionalPage` identifies the source-only contract without adding template discovery |
| Response plus handled boolean | Value or `None`; exceptions are terminal | `adapt`: Python `None` expresses decline without redundant boolean/value combinations; same application capability |
| `content.Config`, `Pages`, `New`, `Check`, `Resolve` | `content.Config`, `Pages`, `new`, `check`, `resolve` | `adapt`: Python casing, normal exceptions, and Path ownership |
| External FS / embedded FS | Trusted Path / resource directory held by `as_file` | `adapt`: application-owned package data and resource lifetime replace Go embedding |
| GFM, heading IDs, and trusted raw bodies | Qualified Python Markdown parser and private Markup boundary | `preserve` features, `adapt` parser output/slug details; no byte-identical Goldmark or GitHub promise |

## 5. Desired Behavior

### Public core surface

Add an immutable, frozen, slotted `AdditionalPage` in `_render.py`, exported from
`pyganini`. Its fields are:

```python
body: str
metadata: PageMetadata = PageMetadata()
layout: Mapping[str, object] = <empty mapping>
status_code: int = 200
headers: Mapping[str, str] = <empty mapping>
```

Use dataclass factories for defaults, the current metadata validation, immutable
mapping copies, status validation, and reserved-header rules. `body` must be a
string and is explicitly trusted HTML. It is not a Jinja template and is never
interpreted as template source. No `context`, template name, request object, or
renderer selector belongs to this value. Empty generic bodies are permitted;
the content package separately rejects blank authored files.

`Page`, `PageRouteResponse`, `FragmentRouteResponse`, and `RouteResponse` keep
their current meaning. Declared route and error callbacks cannot return
`AdditionalPage`. Additional pages have no fragments or actions.

Add and export this callback alias from the existing dispatch owner:

```python
type AdditionalPageSource = Callable[
    [Request],
    AdditionalPage | Response | Awaitable[AdditionalPage | Response | None] | None,
]
```

The generated factory adds
`additional_page_source: AdditionalPageSource | None = None`. Validate the
callable at router construction using the existing callable/signature model
with one request argument. Invoke sync sources in an AnyIO worker; await async
sources on the existing event loop. Never create an event loop or change worker
limits. A callback is called at most once per ordinary HTTP miss.

### Content package

Add `pyganini.content` with exactly these public owners:

```python
@dataclass(frozen=True, slots=True)
class Config:
    root: Path


class ContentError(RuntimeError):
    path: str  # POSIX source-relative path, or '.'
    rule: str


class Pages:
    def resolve(self, request: Request) -> AdditionalPage | None: ...


def new(config: Config) -> Pages: ...
def check(root: Path) -> None: ...
```

`Pages` has private state; applications construct it through `new`. `new` calls
the same full-tree validation as `check`, captures an absolute root, and returns
one sync resolver. `Config.root` and `check` require a `Path`; invalid argument
types raise `TypeError`. Filesystem and recognized-entry failures raise
`ContentError` with source-relative evidence and retained causes, without body
bytes or absolute paths in the message. The root must exist and be a directory.

Example bootstrap, inside the application's existing factory/lifespan:

```python
from pathlib import Path
from pyganini import content
from app._pyganini.asgi import create_router

pages = content.new(content.Config(root=Path("content")))
router = create_router(additional_page_source=pages.resolve)
```

Applications that need layout data compose it explicitly, for example with
`dataclasses.replace(page, layout=build_layout(request, ""))`. `resolve` injects
no request, navigation, URLs, assets, auth, or dependencies into layouts.

### Layout and middleware ownership

Derive a deterministic private miss plan from the existing `RouteGraph`:

- Include only original live `app/routes` nodes with no dynamic ancestry and
  no `app/mounts` source. Include layout-only and middleware-only nodes.
- Select whole-segment static prefixes against the original graph-local URL
  path before middleware. `/privacy` matches itself and descendants, not
  `/privacy-extra`. Matching must not clean, redirect, infer parameters, or
  reselect ancestry after middleware changes a scope.
- Compose middleware root to leaf and layouts outer to inner. Construct fresh
  Starlette middleware instances for each router through public ASGI/Router
  interfaces. Reuse source capture, tuple validation, and diagnostic owners.
- Do not import or instantiate otherwise unused source-only middleware when
  `additional_page_source` is `None`. Its static evidence is still checked.
  Only add source-only layout names to runtime environment validation when a
  source is configured; ordinary route/error template checks remain as they are.
  Check/generate still validate every declared source layout statically.
- The selected chain encloses resolution, successful writing, source errors,
  and declined final not-found handling. Exceptions from middleware itself use
  the existing outer generated error boundary and response-start rules.
- No generated endpoint, route inventory row, URL helper, inferred navigation
  identity, or new path parameter is created. Preserve any host-owned scope.

Ordinary static/dynamic/mounted matches, method mismatches, explicit existing
invalid-path rejections, selected endpoint 404s/errors, and non-HTTP scopes never
invoke the source. A source may return any concrete Starlette response, which
bypasses layouts and retains direct response semantics. `None` reaches existing
final 404 handling exactly once, inside the selected middleware. A returned
page with status 404 is handled and does not fall through.

### Rendering and errors

Refactor only the existing Jinja layout composition owner so a finished body can
enter the same layout chain without a page-template stage. No built-in Jinja
template or loader adapter is needed. Mark the trusted body safe privately;
metadata and ordinary layout strings stay autoescaped. Buffer body/layout
rendering before response start and use existing HEAD suppression.

A source exception, invalid return, or render failure is terminal and follows
the configured `RouteErrorHandler`. Its `Page` error presentation uses the
declared root error template and eligible live root layouts only, excluding
section and mounted-root layouts. Error fragments remain layout-free. `None`
delegation, non-HTTP exception re-raise after a handled response, HTTP status and
header preservation, callback failures, and post-start exceptions keep the
current generated error semantics. Do not add a ContentError-specific writer,
status registry, built-in error page, logging policy, or swallowed exception.

Inspection marks eligible layouts using existing evidence. There is no invented
page-template marker for authored content. Content bodies acquire neither route
identity nor framework component markers.

## 6. Locked Decisions and Invariants

- One optional, application-composed source callback; no registry or chain API.
- One graph and one Jinja layout writer; content packages never import generated
  application modules, `_route_graph`, `_dispatch_generation`, or `_inspection`.
- Existing `Page` stays template-backed. `AdditionalPage` is confined to the
  source branch; its naming adaptation above is part of owner acceptance.
- `content/` stays outside `app/` in examples. Packaged resource content uses a
  separate application-owned data package, not route source or generated files.
- Sync loading and Markdown work finish in the source worker before Jinja layout
  rendering. Each render uses request-local parser state; no shared mutable
  document/heading state or last-known-good cache.
- Keep Jinja, Starlette, Python support, uv, and current quality boundaries.
- Content is trusted like application templates. `check` is operational
  validation, not an HTML safety check. The article wrapper is not containment.

## 7. Rules and Failure Modes

### Entry and filesystem rules

Every page directory contains `page.json` and exactly one of `body.md` or
`body.html`. Any recognized file claims an entry; incomplete or duplicate-body
entries are errors. Containers with no recognized file do not resolve. Recognized
files at the content root are rejected; `/` is never a content page.

Directory segments match `[a-z0-9]+(?:-[a-z0-9]+)*`. Recursively validate the
complete tree in lexical order at startup/check. Reject symlinks, Windows reparse
points, and special files, including unrecognized entries. Ordinary unrecognized
regular files are ignored and never served. Check the configured root and each
traversed descendant directory; this does not reject operating-system aliases
above the root. Reject links/non-regular recognized files before reading. Check the
opened file type and read at most limit plus one bytes; never read an unbounded
file based solely on earlier stat size. Trusted deployment and application-owned
updates remain the concurrency boundary; no hostile-writer confinement claim.

Metadata is one UTF-8 JSON object: required nonblank string `title`, optional
string `description` defaulting to `""`. Unknown/duplicate fields, nulls,
non-string values, trailing values, malformed JSON, and invalid UTF-8 fail.
Metadata is at most 16 KiB; each source body at most 512 KiB; rendered Markdown
HTML at most 2 MiB measured in UTF-8 bytes before the article wrapper. Boundaries
are inclusive. Empty or whitespace-only bodies fail. Preserve HTML text and line
endings using byte reads and UTF-8 decoding, without HTML serialization.

`resolve` reads traversed directories and recognized files anew for each valid
GET/HEAD request, validates the requested entry, and constructs the body. It
does not walk unrelated descendants per request. Missing directories, missing
pages, organizational containers, unsupported methods, and invalid identifiers
decline before unnecessary file access. Permission/read failures, links/special
files on traversed paths, or recognized incomplete/invalid entries are terminal.
Multi-file saves are not transactional; invalid live edits fail until repaired.

### URL and mount rules

Use trusted ASGI `root_path` and public request scope, with the current base-path
normalization contract, to derive graph-local paths. Strip an actual whole-prefix
decoded `root_path` when present; otherwise use the already-local scope path.
Use the corresponding original `raw_path` evidence when provided. Raw/decoded
paths must agree after UTF-8 percent decoding; map the decoded mount-prefix byte
boundary to the corresponding unchanged raw suffix. Reject escaped content
segments, dot/empty segments,
backslashes, trailing slashes, non-ASCII segments, and normalization attempts.
Escapes in the host's base prefix do not invalidate a canonical local identifier.
Query strings do not affect entry lookup. Without optional ASGI raw evidence,
validate the decoded identifier only; do not claim to detect erased escape
provenance. Document this ASGI adaptation and test both evidence modes.

Static miss ancestry uses the original path evidence and the same base-path
derivation, without applying the content segment grammar to arbitrary custom
sources. Do not introduce proxy-header inference. Verify a nested host mount
and an encoded/Unicode host prefix as well as the root mount.

### Markdown and optional dependencies

Propose a `content` extra, with these direct ranges and locked initial candidates:

```text
markdown-it-py>=4.2.0,<5        # initial probe: 4.2.0
mdit-py-plugins>=0.6.1,<0.7     # initial probe: 0.6.1
linkify-it-py>=2.2.0,<3         # initial probe: 2.2.0
```

Only explicit `pyganini.content` use imports this parser family. Normal
`import pyganini`, generated routers, and a plain wheel install need no content
extra. A missing extra produces an actionable ImportError naming
`pyganini[content]`. Do not re-export/import the package eagerly in root
`__init__`. `from pyganini import content` remains normal Python submodule import.

Use `MarkdownIt("gfm-like", {"html": True})`, disabled task-list inputs, and
anchors for heading levels 1 through 6 without permalink decorations. Explicitly
allow authored link/image protocols through a private override of the parser's
public validation method. HTML files pass through unchanged. Markdown parsing
may normalize its own syntax/output; there is no rendered-HTML parse or sanitizer.

The parser's common syntax, tables, strikethrough, task lists, HTTP(S)/www/email
autolinks, raw HTML, and document-local heading IDs are the supported feature
contract. The anchor plugin's default slug rule and duplicate suffixes are used;
common `Privacy part one` headings yield `privacy-part-one`, then
`privacy-part-one-1`. Raw HTML headings are not rewritten. No byte-identical
Goldmark/GitHub slug, full GFM conformance certification, syntax highlighting,
math, footnotes, or plugin API is promised. Content receives
`<article class="pyganini-content">...</article>` and no framework CSS.

The standard library/Jinja do not parse Markdown. A local parser or linkifier
would be larger and less reliable. The extension package avoids maintaining
task/anchor algorithms; the linkifier supplies the proved autolink families.
Their optional installation, patch/minor bounds, typing and distribution tests,
and absence from core imports bound their maintenance cost. Add no other direct
runtime dependency or renderer abstraction without a spec update.

### Diagnostics

Reserve `PYGANINI023 additional-page-source` for source factory validation,
invalid return values, and source invocation contract failures; keep normal
application exceptions as retained causes and existing error-hook inputs.
Include phase, callback evidence where available, graph-local request path,
eligible layout/middleware source positions, and generated file evidence.
Do not expose body/metadata values. Use existing `PYGANINI018` middleware,
`PYGANINI015` render, and `PYGANINI019` error-handler owners for their failures.
Content errors use `ContentError.path`/`rule`, independent of CLI diagnostics.
Recheck code allocation before implementation; a collision is a stop condition.

## 8. Existing Patterns to Reuse

- `_route_graph.py`: live declaration-free nodes and source/layout/middleware
  facts; no new source scan or graph.
- `_dispatch_generation.py`: factory annotations, deterministic literals,
  middleware consumers, runtime imports, generated ownership.
- `_dispatch.py`: controlled callable validation, sync offload, async invocation,
  selected-route error semantics, public Starlette composition.
- `_render.py`: immutable render values, safe header/status validation,
  autoescaping, buffered layout writer, worker offload, inspection evidence.
- `_url_binding.py`: decoded base-path normalization; no proxy header guessing.
- `_filesystem.py`: understand its classification/no-follow patterns; keep its
  generated-root ownership out of content. Do not turn it into a public FS layer.
- `tests/conftest.py`, `typing_contract_support.py`, and existing distribution,
  dispatch, middleware, render, and host test fixtures.
- Full-feature `build_layout`, error hook, host mount order, neutral example
  branding, and independently generated example products.

## 9. Implementation Touchpoints and Agent Containment

Expected framework paths: `src/pyganini/{__init__,_dispatch,_dispatch_generation,
_render,_url_binding,_route_graph,_template_references,_generation}.py` and new
`src/pyganini/content/{__init__,_files,_markdown}.py`. The content package owns
only loading/checking/conversion, depends on render values, and is not imported
by generation, core bootstrap, or inspection.

Expected test owners: new `tests/test_content.py`,
`tests/test_additional_page_source.py`, `tests/test_content_typing.py`, matching
positive/negative `tests/fixtures/content_consumer_*.py`, and affected existing
dispatch-generation, render, route-graph, package-install, generation, and
inspection tests. Use temporary trees, small ASGI hosts, and installed-consumer
fixtures; no hand-written generated modules.

Packaging/check owners: `pyproject.toml`, uv-managed `uv.lock`,
`.github/workflows/ci.yml`,
`probes/qualification/qualification_probes/scenario_worker.py`,
focused worker tests and `probes/qualification/README.md`. Update root quality
sync to install all extras, add the content example to server-example coverage,
and extend Q010's public-consumer list; preserve
scenario IDs, verdicts, gates, and report schema.

Example owners: new `examples/content_pages/` with `app/`, `content/`,
application-owned packaged test data, tests, README, pyproject, uv lock, and
normal generated products; full-feature `app/{main,errors}.py`,
`app/routes/handlers.py`, relevant static layout/middleware-only source,
`content/`, pyproject/lock, README, and tests. Regenerate every affected existing
example's `app/_pyganini/` via its locked project commands.

Doc owners: repository `README.md`; `docs/user/{README,content-pages,rendering,
middleware,errors,project-layout,installation,cli}.md`;
`docs/arch/{content,rendering-responses,generated-asgi-dispatch,
application-composition,route-graph,project-package-generation,parity}.md`;
public package docstrings; this child and its umbrella.

These are expected paths, not an exhaustive deny list inside accepted behavior.
Explicit exclusions: Goldr repository, unrelated projects, JS/HTMX upgrade,
development reload tooling, release workflow/version/tag changes, new CLI/starter
commands, unrelated route/navigation/asset behavior, second renderers, and broad
refactors. No commit, staging, push, publication, or deployment authority.

Stop for new public APIs/dependencies, a required FS adapter, unresolved mount
evidence, a second graph, unsupported dependency combinations, altered error or
response-start semantics, or a disproved contract. Update and reaccept the child.

## 10. Proposed Design

Generate immutable static prefix plans, middleware binding evidence, eligible
layout evidence, and factory wiring from graph nodes. Build a source-aware
Starlette router/default HTTP miss application through public interfaces. Select
the plan once, run its captured middleware around the source writer and final
404, and retain the current endpoint path-before-method behavior.

Keep source invocation and validation in `_dispatch.py`, trusted-body values and
shared layout writing in `_render.py`, and file/Markdown work in `content`.
Factor the existing layout loop only as needed to accept either a rendered
declared template or a finished additional body. Do not construct a Jinja
environment in the content package or copy the layout algorithm.

Keep `Config` and `Pages` small. Use bytes, ordinary JSON duplicate-key hooks,
stdlib file-kind checks, bounded reads, and source-relative errors. Hold packaged
content with `with importlib.resources.as_file(resources.files(data_package)
.joinpath("content")) as root:` for the full server/lifespan duration. The
application owns package inclusion and resource cleanup; Pyganini owns no
embedding, extraction cache, or shutdown hook.

## 11. Implementation Plan

### Phase A: Values and generated source contract

- [x] Add typed `AdditionalPage` and `AdditionalPageSource`, validation/docstrings,
  and positive/negative consumer checks under mypy and Pyright.
- [x] Add smallest failing tests for ordinary misses, terminal values/errors,
  nil source, sync/async responsiveness, matched-route and 405 ownership.
- [x] Generate source factory wiring and graph-derived static miss plans;
  declaration-free and zero-endpoint applications work without dummy routes.
- [x] Reuse Jinja layout writing and existing error semantics; prove metadata
  escaping, raw body preservation, HEAD, direct/streaming responses, and the
  absence of invented content page markers.
- [x] Update rendering/composition/errors docs with those implemented contracts.

### Phase B: Trusted filesystem content

- [x] Add the optional extra using uv and the exact content module surface.
- [x] Add focused valid HTML/Markdown, nested/container, live edit/new page,
  recovery, and package-resource tests.
- [x] Prove metadata/body limits, duplicate/unknown/null JSON, UTF-8, blanks,
  symlink/special-file rejection, bounded reads, missing vs operational failure,
  canonical URLs, mount prefixes, and raw-evidence modes.
- [x] Prove GFM families, heading levels/duplicates/reset/concurrent isolation,
  raw HTML and trusted destinations, and rendered UTF-8 size limits.
- [x] Update content/package docs and check-only application usage with no new
  framework CLI command or sanitizer claim.

### Phase C: Examples, distributions, and qualification

- [x] Add independent content example with generated-route precedence,
  HTML/nested Markdown, section-only layouts/middleware, generic error logging,
  check-only mode, and neutral styles; all generation is command-owned.
- [x] Wire full-feature content with explicit `build_layout` mapping and no
  inferred navigation; preserve Starlette/FastAPI hosts and existing workflows.
- [x] Extend installed wheel and sdist-derived wheel tests: plain core import
  without content dependencies, actionable missing-extra import, extra-enabled
  content source, and packaged content from outside the source checkout.
- [x] Update locked CI/Q010 consumers and sync, run required checks, and record
  candidate-specific evidence without changing existing qualification gates.
- [x] Regenerate affected example output, update parity/docs, and tick only
  verifiable items.
- [x] Owner accepts the completed implementation; release stays gated.

## 12. Acceptance Criteria

The phases above are complete. Focused evidence proves static/dynamic/mounted
routes, method mismatches, endpoint 404/errors, and explicit path rejections never
call the source. Sources are called once, can short-circuit or decline, and are
responsive for sync/async callables. Prefix selection is deterministic, handles
segment boundaries and mount bases, excludes dynamic/mounted ancestry, and is
not changed by middleware scope mutation. Source-only bindings fail closed with
localized evidence. Every supported value/error/HEAD/inspection path uses the
existing response invariants. Files and parser checks cover reachable failures
and both supported interpreters. No content entries leak into inventory/helpers.

## 13. Validation Commands

Planning changes only Markdown under `docs/spec`; run handoff review and
`git diff --check`. The commands below define implementation requirements. Candidate evidence is
recorded in the implementation evidence section; an unrun gate remains open.

From the repository root:

```text
uv lock
uv sync --locked --all-groups --all-extras --python 3.14
uv run --locked --all-extras --python 3.14 pytest -q tests/test_content.py tests/test_additional_page_source.py tests/test_content_typing.py tests/test_render.py tests/test_dispatch_generation.py tests/test_dispatch.py
uv run --locked --all-extras --python 3.14 ruff format --check .
uv run --locked --all-extras --python 3.14 ruff check .
uv run --locked --all-extras --python 3.14 mypy src/pyganini
uv run --locked --all-extras --python 3.14 pyright src/pyganini
uv run --locked --all-extras --python 3.14 pytest
uv sync --locked --all-groups --all-extras --python 3.13
uv run --locked --all-extras --python 3.13 pytest
git diff --check
```

From each changed example root, including `examples/content_pages` and
`examples/full_feature`, on each Python line (substitute 3.13 for 3.14):

```text
uv lock
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 pyganini assets dist
uv run --locked --python 3.14 pyganini generate
uv run --locked --python 3.14 pyganini check
uv run --locked --python 3.14 pyganini assets check
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy app tests
uv run --locked --python 3.14 pyright app tests
uv run --locked --python 3.14 pytest -q
```

The new example must enable fingerprinted CSS so these asset commands apply.
Its exact app-owned check-only entrypoint is
`uv run --locked --python 3.14 python -m app.main --check-content`.
Root package tests own distribution installation on both interpreter lines.
From `probes/qualification`, use the existing locked tool environment:

```text
uv sync --locked --python 3.14
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy qualification_probes tests
uv run --locked --python 3.14 pyright qualification_probes tests
uv run --locked --python 3.14 pytest -q
PYGANINI_QUAL_OUTPUT=$(mktemp -d /tmp/pyganini-content-qualification.XXXXXX)
uv run --locked --python 3.14 python -B -m qualification_probes --pyganini-root /Users/pochkin/Projects/my/pyganini --output "$PYGANINI_QUAL_OUTPUT/evidence"
```

Rebind the explicit candidate path if the accepted implementation uses another
checkout. Verify `SHA256SUMS` from the completed evidence directory. An
unavailable check remains open. Stop every server started.

## 14. Documentation and Example Updates

Document supported content use, explicit layout data, trust, metadata/limits,
external/package deployment, error behavior, and manual refresh in the named
user guides. Maintainer docs describe graph projection, ASGI path evidence,
dependency direction, layout writer, source error boundary, and absence of route
identity. Add full-feature and standalone usage; refresh the capability ledger
only with shipped/qualified evidence. CLI help and generated starter do not gain
content features; CLI docs only clarify source/inventory boundaries.

## 15. Cleanup and Legacy Removal

Remove stale generated products through commands, replace blanket statements
that all misses bypass route middleware, and retain distinctions for nil-source,
matched-method, and invalid-path outcomes. Keep existing Page contracts and no
compatibility aliases for Goldr's obsolete `Fallback`. If implementation is
rolled back, remove the new extra/exports/package and regenerate examples from
restored source together; do not leave source-only middleware partially enabled.
Fold implemented behavior into durable docs before eventual child cleanup.

## 16. Open Questions

No implementer-owned product decision is left open. The owner accepted the
`AdditionalPage` naming/model, optional dependency boundary, trusted-Path
deployment assumption, and documented missing-raw-path adaptation.
Automatic refresh, stable HTMX, Windows supervision, and release are assigned
outside this child. New evidence that changes these decisions is a stop condition.

## 17. Implementation Evidence

Core adds typed `AdditionalPage`/`AdditionalPageSource` and a generated miss
branch using the same route graph. Optional content is isolated from plain core
imports. Focused tests cover live reads, strict files/metadata/limits, trusted
Markdown/GFM/anchors, raw mount evidence, source-only layout/middleware plans,
matched and mounted precedence, streaming HEAD/error boundaries, preserved host
scope, ASGI loop responsiveness, and opt-in runtime layout validation. The
original missing behavior and later localized diagnostic/scope regressions had
focused failing evidence before correction.

Positive/negative public consumers pass their intended mypy and Pyright
contracts. Framework source has zero diagnostics under both tools. Built wheel
and sdist-derived wheel tests cover plain installations and the optional extra
on Python 3.13/3.14, outside the checkout, including application-owned extracted
zip resources. Root tests pass 1095 cases with one skip on CPython 3.13.15 and
3.14.7. Ruff, current-state docs, examples, and generated checks pass. The fresh
3.14 run supersedes an invalid run whose environment was switched concurrently.

Standalone content and full-feature tests pass on both lines, including actual
browser authoring proof supplied by the accepted dependent child. Goldr remains
clean at the pinned target. The qualification harness installs all extras in
Q010/Q011 while keeping plain-installation checks independent; the Q011 command
fix has a focused failing regression followed by passing evidence.

The fresh report at
`/tmp/pyganini-parity-qualification.Kt7F42/evidence/report.json` passes all fifteen
scenarios with `PASS_TO_PERFORMANCE_QUALIFICATION`, matching candidate identity,
clean process/resource cleanup, and all checksum entries verified. The umbrella
records the candidate hash and evidence-only closeout boundary. Interrupted
qualification attempts are incomplete evidence, not passing verdicts.

A separate public-API probe at `/tmp/pyganini-content-concurrency-proof.py`
passes on both Python lines. It proves heading levels 1-6, duplicate IDs, four
simultaneous independent renders, and a fresh-render reset. This is disposable
probe evidence in addition to checked-in focused regressions. Final owner
acceptance is recorded after remediation below.

## 18. Independent Review Remediation

The owner's supplied independent review confirms three content defects:
escaped host-prefix separators consumed local path segments; a missing
linkifier bypassed the optional import guard; source error-callback diagnostics
substituted a generated filename or a middleware-mutated path for original
graph-local request evidence. The owner authorized their remediation on
2026-10-03. These fixes implement existing accepted contracts, with no new API,
dependency, or ownership boundary.

Checked-in focused regressions first produced eight failures and ten passes:
escaped ASCII/Unicode prefix cases, a nested generated-source mount retaining
section layouts/middleware, an isolated real import without the linkifier, and
source/middleware/declined error-callback diagnostics after scope mutation.
The corrected content/source suite passes 47 cases. Request bookkeeping retains
pre-existing host values and removes temporary keys afterward. Durable docs
describe the corrected raw boundary and dependency/diagnostic behavior.

The corrected Python 3.14 root suite passes 1105 cases with one skip. The focused
content/source/typing suite passes 51 cases on Python 3.13. Both source type
checkers, all 334 content/render/dispatch checks on Python 3.14, and both example
quality/generated/asset/browser suites on both Python lines pass. The reviewer's
original filesystem mount, missing-linkifier, and callback-diagnostic
reproductions also pass. An example rerun initially referenced an absent browser
directory; the successful rerun uses the installed Chromium runtime.

The prior qualification report in section 17 binds the pre-remediation
implementation. The corrected candidate passes all fifteen scenarios in
`/tmp/pyganini-review-fixes-qualification.0sowu7xk/evidence/report.json`, with
`PASS_TO_PERFORMANCE_QUALIFICATION`, matching initial/final identity, clean
cleanup, and all 31 checksum entries verified. Q011 proves 1105 root cases with
one skip on Python 3.13, matching the local Python 3.14 result. The umbrella
records the corrected candidate hash and evidence-only closeout boundary.
The owner supplied a single-agent focused independent re-review on 2026-10-03.
It confirms all three defects resolved, with no remaining actionable findings
or new confirmed regression within remediation scope. Independent checks pass
334 scoped cases on Python 3.14, 51 content/source/typing cases on Python 3.13,
and 18 additional probes on each line. The probes also confirm optional-free
core/generated imports, render-error path evidence, concurrent diagnostic
isolation, and bookkeeping restoration. The reviewer verifies all 31 report
checksums and only the four declared spec closeout differences, with no
candidate changes during review. Full browser/distribution qualification
remains author evidence; it was not rerun by this reviewer. The owner accepted
the completed implementation on 2026-10-03. Commit, push, publication, release,
and deployment remain separate approvals.
