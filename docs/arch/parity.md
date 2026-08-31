# Goldr parity and Pyganini qualification

Pyganini compares application capabilities and ownership with Goldr. Python,
ASGI, Starlette, Jinja, packaging, and typing require different mechanisms.
Mechanism differences do not establish a parity gap when developers can build
the same application workflow under the accepted ownership boundary.

The current Goldr baseline is `7232062208c2ad19886fd6c75aaf830d94486476`.
Refresh that source comparison before changing a disposition or making a new
comparison claim. The checkout is not a Pyganini dependency.

## Capability ledger

`preserve` keeps the application capability and ownership. `adapt` keeps the
capability through Python-native mechanisms. `defer` retains a concrete open
question. `reject` records a boundary Pyganini will not own.

| Capability | Goldr behavior | Pyganini behavior | Disposition | Evidence owner | Limitation | Next owner |
| --- | --- | --- | --- | --- | --- | --- |
| Project selection, generation, and stale checks | Explicit application root, generated products, and non-writing check | `[tool.pyganini]`, `pyganini generate`, and `pyganini check` own one deterministic generated package | `adapt` | [Project and package generation](project-package-generation.md) | Several changed products use an honest per-file atomic boundary | Qualification and packaging remediation when evidence changes |
| Filesystem routes and declarations | Static route tree with explicit pages, fragments, and actions | One AST-derived `RouteGraph` from `app/routes` and direct `Route = route(...)` declarations | `adapt` | [Route graph](route-graph.md) | Dynamic values containing decoded `/` remain unsupported | Route-graph child after a concrete Starlette-compatible use case |
| Generated dispatch | Generated HTTP dispatch consumes the route graph | Generated public Starlette `Router` values consume the same graph | `adapt` | [Generated ASGI dispatch](generated-asgi-dispatch.md) | FastAPI dependencies and OpenAPI do not define Pyganini routes | None; host integration remains application-owned |
| Pages, layouts, fragments, actions, and direct responses | templ components and generated layout composition | Sync Jinja rendering, explicit `Page` and `FragmentResponse`, and public Starlette responses | `adapt` | [Rendering and responses](rendering-responses.md) | Jinja does not provide templ-equivalent compile-time HTML checks | Typed layout keys remain deferred |
| Generated URL interfaces | Generated route-shaped URL helpers | Generated typed Python namespaces, dynamic binders, and `.path` values | `adapt` | [Generated URL interfaces](generated-url-interfaces.md) | Decoded slash values do not round trip through Starlette dispatch | Route and URL child after a supported matcher design exists |
| HTMX forms and request data | Visible HTMX markup with route responses and parsed forms | Visible Jinja `hx-*`, direct Starlette forms, and bounded immutable captured request data for sync or async actions | `adapt` | [HTMX and forms](htmx-async-forms.md) | Applications own validation, uploads, and response policy | Application code unless another shared wire need appears |
| Shared route implementations | Kit routes share handlers and templates across owners | `route_kit` keeps shared Jinja and handlers explicit | `adapt` | [Route kits](route-kits.md) | Shared code receives no framework dependency container | None |
| Mounted route subtrees | Live owners select reusable filesystem route sources | `route_mount` selects `app/mounts` source with generated binding | `preserve` | [Mounted routes](mounted-routes.md) | Live owners retain middleware, auth, and state policy | None |
| Route inspection | Commands expose declaration metadata, mounted selection, route, layout, reference, and render evidence | Source-only list, layouts, explain, refs, and render-units commands consume `RouteGraph`; list and explain report Python handler and root error-render evidence | `adapt` | [Route inspection](route-inspection.md) | Inspection does not import handlers or render Jinja | New inspection child only for graph-backed application evidence |
| Navigation | Generated routes provide explicit trail and destination data with a handler base path | Generated destinations plus request-scoped `nav(request)` values use effective ASGI `root_path` | `adapt` | [Navigation](navigation.md) | Pyganini does not own proxy-header policy, browser history, or session return stacks | Application host and code |
| Live route middleware | Live route policy composes with generated dispatch | Live `middleware.py` composes application-owned Starlette middleware inside selected generated routes | `adapt` | [Application composition](application-composition.md) | Host, static, lifespan, and unmatched router outcomes stay outside route middleware | Application host |
| Layout-aware generated error presentation | Custom error components use generated layout composition | One optional `RouteErrorHandler` returns existing render values; static root templates use root or selected live layout evidence and appear in source inspection | `adapt` | [Generated ASGI dispatch](generated-asgi-dispatch.md) | Host routes, static files, lifespan, post-start failures, and content policy stay application-owned | Application code for error content policy |
| Development loop | Goldr integrates generation, templ work, proxying, and browser reload | `examples/full_feature/dev.py` owns generate/check before Uvicorn replacement | `adapt` | [Full-feature development workflow](../../examples/full_feature/README.md) | Browser refresh stays manual; native Windows supervision is absent | Development-loop child after another application proves demand |
| CSRF wire helpers | Optional guard, middleware, token validation, and helpers | `pyganini.csrf` supplies a Python guard and ASGI middleware; Jinja keeps markup visible | `adapt` | [CSRF](csrf.md) | Applications own secrets, failure policy, and middleware placement | Application code |
| SSE wire helpers | Typed events, comments, IDs, and retry fields | `pyganini.sse` encodes wire frames for application-owned `StreamingResponse` | `adapt` | [SSE](sse.md) | Pyganini owns no subscriber, replay, flush, or stream lifecycle | Application code |
| Named SSE browser events | Optional named-event swap helper and fixed helper serving | `pyganini.browser` provides one HTMX 4 hook and an explicitly mounted fixed-resource app | `adapt` | [Browser helpers](browser.md) | Applications own stream production, URLs, mounting, CSP, cache policy, and deployment | Application host and templates |
| Runtime template inspection | Generated render boundaries and an optional development overlay | Typed router modes emit deterministic Jinja render markers; the shared browser app serves an application-enabled overlay helper | `adapt` | [Template inspection](../user/template-inspection.md) | Static inspection remains source-only; direct responses and application policy stay outside instrumentation | Application development configuration and host |
| Fingerprinted assets | Final build input projects to SHA-256-named browser assets | `pyganini assets` projects `assets/build` and generates typed lookup metadata | `adapt` | [Assets](assets.md) | Applications own compilation, static serving, cache policy, and deployment | Application asset pipeline |
| Bounded React and Svelte islands | Route-local islands integrate with HTMX lifecycle | Independent examples own Vite, mount and teardown, JSON calls, and state | `preserve` | [Client islands](../user/client-islands.md) | Pyganini provides no shared island API, hydration, or client router | Application frontend |

## Reconciled capability decisions

These five related capabilities have final current dispositions. None remains
deferred:

| Capability | Final disposition | Preserved capability | Python-native adaptation and rejected ownership |
| --- | --- | --- | --- |
| Navigation under a public base path | `adapt` | Canonical navigation, URL helpers, custom trails, and return targets honor one effective base path without changing graph-local matching. | Request navigation reads trusted decoded ASGI `root_path`; applications bind generated URLs explicitly. Pyganini rejects a Go-style handler option, proxy-header inference, browser-history ownership, and session return stacks. |
| Layout-aware generated error presentation | `adapt` | Application callbacks may select pages, fragments, or direct responses; root and matched pages use the correct layouts, fragments use none, and response-safety rules remain intact. | Static Jinja template facts and one typed callback replace concrete templ components and multiple generated hook fields. Pyganini rejects built-in error content, a status registry, and ownership of failures outside generated dispatch. |
| Runtime template inspection | `adapt` | Off, comments, and overlay modes identify page, layout, fragment, embedded-fragment, and labeled-component boundaries in development. | A typed `StrEnum`, generated Jinja marker facts, call-block helpers, and the shared fixed-resource browser app replace Goldr's Go and templ surfaces. Pyganini rejects automatic helper mounting, generated script insertion, and treating source-only enumeration as runtime parity. |
| Route metadata and richer source inspection | `adapt` | Optional names, titles, opaque labels, declaration evidence, and included or excluded mounted candidates remain statically inspectable. | Python literal `RouteMeta`, AST positions, Jinja templates, and Python handler bindings replace Go manifest and adapter evidence. Pyganini rejects a second route graph, handler imports during source inspection, and generated Go adapter concepts; root error-render evidence is a Pyganini extension. |
| Named SSE browser events and fixed helper serving | `adapt` | Applications can opt into named-event swaps through an explicitly mounted, cache-aware helper while retaining visible HTMX markup. | One HTMX 4 hook and `pyganini.browser` fixed package resources replace Goldr's older hook and serving mechanics. Pyganini rejects ownership of stream production, subscribers, replay, authorization, mounting, CSP, cache policy, and deployment. |

Earlier children deferred rendering values, route errors, route middleware,
URL helpers, navigation, inspection, mounted routes, sync request data, CSRF,
assets, and client-island examples to named successors. Those successors have
shipped, so this ledger records their current dispositions instead of retaining
the old deferrals.

## Comparative workflows

### Route addition and refactor

Pyganini reads route declarations without importing handlers. `pyganini check`
reports stale generated files without writing, and `pyganini generate` replaces
the complete route and URL products from one `RouteGraph`. Q030 and Q031 prove
static-page addition and dynamic-parameter rename through an installed wheel,
both type checkers, inspection, and request dispatch.

Goldr generates its route wiring and URL helpers, then Go compilation and templ
generation check the application program. Pyganini preserves Goldr's explicit
generate/check workflow and adapts compile-time evidence to AST checks,
generated Python, mypy, Pyright, controlled imports, and runtime tests. Pyganini
does not adopt a startup-owned discovery model because it would weaken
pre-start static inspection and generated-state checks.

### Invalid declaration and import

Pyganini rejects unsupported declaration syntax and route collisions before it
mutates generated products. Q040 and Q041 prove exact, same-shape, and keyword
expansion failures from public commands. Controlled imports remain a separate
startup phase.

Goldr uses scanner diagnostics and Go or templ compilation for equivalent
invalid source. Pyganini keeps fail-closed startup instead of serving a partial
route tree after an import or declaration failure.

Functional qualification initially found two qualification-contract mismatches
rather than production defects. The implemented and owner-accepted Q042/Q043
closure child corrected the harness to the existing production contracts. Q042
requires graph-backed commands to reject a deleted declared template early with
`PYGANINI009 route-filesystem`, without route JSON, a traceback, or generated
mutation. Q043 keeps source inspection import-free and requires generated ASGI
import to raise `PYGANINI012 route-import` while preserving the application
`RuntimeError` as its direct cause and retaining the application traceback
frame. Q044 keeps its separate request-time propagation contract. The accepted
complete passing report is the current functional ledger state; the earlier
findings verdict remains historical provenance.

### Development refresh

Pyganini's full-feature watcher runs `generate` and `check` before it replaces the
application-owned Uvicorn process. A failed preparation keeps the working
server. Jinja observes template content at request time, and developers refresh
the browser by hand. Asset source compilation stays outside the watcher.

Goldr coordinates its generator with templ and provides proxy and browser
reload integration. Pyganini retains the current application-owned loop until
another real application proves that a shared command or browser channel
reduces more work than it adds.

## Application-owned boundaries

Pyganini does not own authentication, authorization, sessions, persistence,
dependency injection, an ASGI server, static-file serving, cache policy,
deployment, logging, or release policy. Starlette and FastAPI hosts compose the
generated router while retaining those responsibilities.

Pyganini also rejects SPA routing, hydration, framework-owned browser state, a
client component registry, and generated island JavaScript. Applications may
own bounded client islands and their complete build and lifecycle bridge.

FastAPI decorators, dependencies, and OpenAPI remain host surfaces. Pyganini
handlers use the accepted Starlette request and route contracts. Jinja remains
the only built-in renderer; Pyganini makes no claim that it provides templ's
compile-time guarantees.

## Open deferrals

| Deferral | Current boundary | Promotion evidence | Next owner |
| --- | --- | --- | --- |
| Browser reload and proxy | Manual refresh in the application-owned loop | A second application demonstrates repeated material cost and a bounded same-origin channel | Development workflow child |
| Generic development command | Each application owns its server and watcher entry point | Two applications need the same fixed generate/check/process contract | Development workflow child |
| Native Windows supervision | Current process-group contract targets macOS and Linux | A supported Windows application supplies process-tree and signal evidence | Platform qualification child |
| Decoded `/` in dynamic values | Starlette dispatch uses decoded paths | A public matcher design proves generation and dispatch agreement without a second route model | Route and URL child |
| Typed layout-data keys | Layout data is an immutable string-keyed mapping | Two layouts share a stable public key contract that typing can simplify | Rendering child |
| Performance claims | No comparative Pyganini speed claim exists | A separate accepted methodology controls environment, workload, and thresholds | Performance qualification child |

## Functional qualification

The latest accepted complete qualification is the 2026-08-28 evidence at
`/tmp/pyganini-qualification-complete.IAgw0y/evidence`. All fifteen scenarios
passed on CPython 3.14.7 and 3.13.15, including Q080 final identity and cleanup,
and the report returned `PASS_TO_PERFORMANCE_QUALIFICATION`. All thirty-one
published checksum entries verified. Initial and final combined candidate
SHA-256 were both
`548ab0318a2609c594e5a6ed6b3316a6ac763d5cbb9f0fbcf9d459e8ce587c26`,
the diff SHA-256 was
`97708e252aa5498e8a33fa0254ae61f23f59357fa6126ab07b91cafa6cd52725`,
and the disposable commit was
`6b9cf6645ecde6254455cba6521811c7436011c5`. The report binds `main` at
`3a998701e262cc37e2657863e6965ddee8a611e1`, ten commits ahead of
`origin/main`, to the six-file unstaged umbrella-review remediation candidate.
Initial and final identities matched, the index and unmerged sets remained
empty, and the report recorded no infrastructure or cleanup error. The project
owner authorized and accepted this fresh qualification phase on 2026-08-28.
A subsequent fresh independent review covered all 235 committed-range paths,
all six unstaged remediation paths, and the resulting live repository. It
returned `CLEAN - READY FOR OWNER UMBRELLA-CLOSURE DECISION` with no material
findings. The project owner accepted that review and explicitly closed the
umbrella on 2026-08-28. Staging, commit, push, publication, and release remain
separate and unauthorized.

The first post-Track-16 attempt exposed a missing off-by-default inspection
setting in the full-feature FastAPI host and stale generated ASGI products in
both client-island examples. After the application fix and framework-owned
regeneration, focused Q001, Q060, Q070, and Q080 evidence passed with matching
identity and verified checksums before the complete passing rerun. No
performance claim follows from this functional result.

The earlier 2026-08-25 qualification matrix returned
`FINDINGS_REQUIRE_REMEDIATION` against Pyganini `main` at
`171bdd110e622d4af6a97324cf030b9555c3c8fc` plus the accepted unstaged
qualification candidate. The external `pyganini.qualification.v1` report records
the candidate's combined SHA-256 because embedding that self-referential value
inside the candidate would change it.

Twelve scenarios passed. Q010 found that the accepted root mypy and Pyright
commands include intentional invalid-consumer fixtures and test-only negative
typing calls, so both commands return findings even though packaging tests and
artifact builds pass. Q042 and Q043 found the phase mismatches described
above. Initial and final candidate identities matched, Q080 cleanup passed, and
the evidence checksums verified. The evidence binds the disposable Git commit,
attributes the distribution build to Q001, and records final identity and
cleanup facts in Q080. The findings belong to the root typing qualification-
command, missing-template phase-contract, and controlled-import exception-
propagation successor boundaries. Performance qualification, release work, and
publication remain closed.

The qualification owner accepted the completed harness, parity ledger, and
findings-bearing evidence on 2026-08-25. That acceptance closes the
comparative-workflow qualification child as implemented; it does not turn this
result into a passing functional verdict. At that gate, the three successor
boundaries and the umbrella's passing-verdict item remained open.

### Q010 focused successor

The accepted Q010 successor separates strict root source analysis from focused
public-consumer typing evidence. Q010 now runs source-only mypy and Pyright
commands, then focused CSRF, SSE, and generated-asset consumer tests under both
checkers. Expected-negative results must contain the intended signature
evidence and must not contain missing-import, unknown-type, or checker-setup
failures. Generated asset consumers run only after the production asset writer
creates their generated module in a disposable application.

Author validation passed on CPython 3.14 and 3.13. A focused external
`pyganini.qualification.v1` run at
`/tmp/pyganini-q010-qualification.NdewRQ/evidence` passed Q001, Q010, and Q080,
verified every published checksum, and returned
`PASS_TO_PERFORMANCE_QUALIFICATION`. The report binds Pyganini `HEAD`
`a9b3e11906476d41a975af81a4eefde9f4ee114a`, combined candidate SHA-256
`a50af4b60bda423564e54bd5997045409472b133cd357112e50ce5210debc7b8`,
and disposable commit `99e3281fd7b4ee67df9fd6fea935f8f523bdf8e9`. Q010 exited `0` in 47,951
milliseconds with clean process cleanup and removed temporary state.

This focused result was author evidence for the Q010 implementation candidate.
By itself, it did not revise the retained full `FINDINGS_REQUIRE_REMEDIATION`
verdict, close Q042 or Q043, authorize performance qualification, or satisfy
the independent-review and implementation-owner-acceptance gates.

The first independent findings-only review returned
`Q010_IMPLEMENTATION_REVIEW_FINDINGS`. It found that the expected-negative
classifiers did not independently prove both CSRF `validate` arguments, every
SSE misuse, or the intended semantic family for each asset misuse. Review
remediation replaces ambiguous flat markers and line-only checks with complete
mypy and Pyright diagnostic-block contracts. Five mutation-style regressions
prove missing boundaries and unrelated same-line errors are rejected.

Post-remediation author validation passed 18 focused consumer cases and 833
tests with one skip on each supported Python line. The replacement external
evidence at `/tmp/pyganini-q010-rereview-final.K16Img/evidence` is checksum-valid and
returned `PASS_TO_PERFORMANCE_QUALIFICATION` for Q001, Q010, and Q080. It binds
combined candidate SHA-256
`4c3ac038f9eca6874974759ef51b0d4c9a02c59e8b58d9ed323569c337b60f50`
and disposable commit `af638ee5a37e19225479c865567c9d3ddfa4d23b`. Q010 exited `0` in 49,493
milliseconds with clean process cleanup and removed temporary state.

The second independent review found that the CSRF and SSE mutation-test
baselines failed for unrelated missing fragments before reaching their claimed
omissions. The final correction first requires each complete synthetic mypy
baseline to pass, then removes exactly one `validate`, `id`, or positional-call
diagnostic block. All four corrected omission cases pass.

Final author validation again passed 18 focused consumer cases and 833 tests
with one skip on each Python line. The acceptance evidence at
`/tmp/pyganini-q010-accepted.c6lHVO/evidence` is checksum-valid and returned
`PASS_TO_PERFORMANCE_QUALIFICATION` for Q001, Q010, and Q080. It binds combined
candidate SHA-256
`b893c657e7068a4bd3f73b59ae53644425bde12f7b291fba339c8b4b7a4b3419`
and disposable commit `3df0ab7e9cda036efd884aa58fa9b91db73cb166`. Q010 exited `0` in 52,001
milliseconds with clean process cleanup and removed temporary state.

The implementation owner accepted the completed Q010 child and directed that
no further review or rereview is required. At that gate, the retained full
verdict, passing-verdict item, Q042, Q043, performance, publication, and release
boundaries remained unchanged. The combined successor below records their
later functional closure.

### Q042 and Q043 focused successor

The project owner accepted the combined functional-qualification findings
closure child on 2026-08-25. Its implementation candidate changes only the
qualification worker, focused worker regressions, and current qualification
records. It does not change production source, public APIs, root tests,
fixtures, generated products, dependencies, locks, or examples.

Q042 now checks `generate`, `check`, and route inventory independently after
deleting the declared fixture template. Q043 separately checks the
source-only commands and the generated startup wrapper, direct application
cause, and retained cause traceback. Complete synthetic baselines plus
one-fact mutation regressions protect every diagnostic, output, wrapper,
cause, sentinel, traceback, and generated-state requirement. The focused and
complete functional reruns remained author evidence until explicit owner
acceptance closed the historical findings verdict.

The fresh independent review found that output-only sentinel evidence could
miss an import that command code caught before exit. Q043 now runs both
source-only installed entrypoints under a task-local Python audit hook and
rejects any handler import attempt, including one followed by caught
`RuntimeError` and exit 0. The owner explicitly waived further review or
rereview after this remediation, then separately accepted the implementation
and complete passing qualification verdict.

Author validation passed both corrected lanes and the complete matrix on
2026-08-25. Focused evidence at
`/tmp/pyganini-q042-q043-qualification.FuyE4N/evidence` contains exactly Q001,
Q020, Q042, Q043, and Q080, all passing. Complete evidence at
`/tmp/pyganini-functional-qualification.Ugp4YE/evidence` contains all fifteen
registry scenarios, all passing, and returns
`PASS_TO_PERFORMANCE_QUALIFICATION`. Both checksum-valid reports bind Pyganini
`HEAD` `dd87cb35e2b85d1bf988a7fbc1871098464c6291`, combined candidate SHA-256
`3597f3a49ed627f9eec7cba2a9371d34fe6dc22a37804c36bf9672ba016addc5`,
disposable commit `9941138fe7fd8032fdccd3379e7cd604b09b02b0`, CPython 3.14.7, and CPython
3.13.15. Initial and final identity matched, process cleanup was clean,
temporary state was removed, and Q080 passed.

The implementation owner and qualification owner accepted both corrected lanes
and the complete `PASS_TO_PERFORMANCE_QUALIFICATION` verdict on 2026-08-25.
That passing report remained the functional ledger state until the fresh
post-Track-16 qualification above. The historical
`FINDINGS_REQUIRE_REMEDIATION` report remains retained provenance, while the
umbrella parity-ledger and comparative-qualification items are complete.
Local commits record the qualification child and its accepted successors.
Performance qualification, push, publication, and release remain closed.
