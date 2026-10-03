# Pyganini Goldr Parity Refresh

Status: completed umbrella; no implementation authority
Created: 2026-10-03
Updated: 2026-10-03

## 1. Authority and Outcome

The owner requested a goal to bring Pyganini to behavioral parity with current
Goldr, beginning with an audit and a handoff-ready specification. `AGENTS.md`
and [Spec Authoring Policy](README.md) govern this work. The owner accepted all
three children on 2026-10-03. Those children authorize their scoped implementation;
this umbrella grants no independent implementation authority. Commit, push,
publication, release, and deployment remain separate approvals.

The owner accepted the completed scope on 2026-10-03 after independent review,
confirmed remediation, and corrected-candidate qualification. The three children
are implemented and the parity goal is closed at the pinned Goldr target.

The goal is complete when the gaps below have accepted implementations,
candidate-specific validation, current-state durable docs and examples, and an
updated capability ledger. A draft, an accepted plan, or a passing dependency
probe is not implementation completion. Performance qualification and release
remain separate gates.

## 2. Pinned Audit

Read-only source comparison on 2026-10-03 used clean worktrees:

- Pyganini: `8231ddd4537ef88b3a33dae3829ba584271aa283`.
- Goldr: `eb8ed60a34922cca988f81f2990ced85e72a81c3`.
- Goldr baseline in `docs/arch/parity.md`:
  `7232062208c2ad19886fd6c75aaf830d94486476`.

The audit reviewed the commit log and changed-file inventory for the complete
Goldr baseline delta, then inspected capability-owning production sources,
durable docs, examples, and focused tests. It does not requalify every previously
preserved capability or constitute a full implementation code review.
Recheck heads and worktree provenance before implementation. A changed head
requires an impact check, not automatic replacement of the pinned target.

| Delta or capability | Current evidence | Disposition and owner |
| --- | --- | --- |
| Filesystem HTML and Markdown content pages | Goldr `content/{content,files,body}.go`; Pyganini has no content package | `preserve` capabilities through the content child; Python filesystem and Markdown mechanisms are `adapt` |
| Additional page source after an ordinary router miss | Goldr generated `AdditionalPageSource`; Pyganini `create_router` has only environment, error handler, and inspection options | `adapt` in the content child, with one explicit sync/async callback |
| Static layout and middleware ancestry for source pages | Goldr generator and `handler_additional_page_source_test.go`; Pyganini loads only middleware used by matched endpoints | `preserve` in the content child, projecting the existing `RouteGraph` |
| Layout-only, middleware-only, and zero-endpoint applications | Pyganini scanner already records declaration-free nodes; generated source dispatch is absent | `preserve` using those existing nodes; no dummy page or second route model |
| GFM features and heading anchors | Goldr Goldmark GFM and auto-heading IDs; no Pyganini Markdown support | `adapt` through a qualified Python parser, with explicit trusted content and slug boundaries |
| External live reads and packaged content | Goldr confined external FS and `embed.FS` | `adapt` to trusted Path roots and `importlib.resources.as_file` lifetime; no hostile-filesystem confinement claim |
| Stable HTMX 4 | Goldr commit `9e40d85` uses 4.0.0; Pyganini examples vendor 4.0.0-beta6 | `preserve` capability through the stable-HTMX child |
| SSE extension and inspector event hooks | Goldr uses `htmx_sse_before_message`, `htmx:after:swap`, and `htmx:after:settle`; Pyganini retains the older hook names | `adapt` existing helpers and browser evidence in the stable-HTMX child |
| CSRF inheritance and visible status policy | Goldr uses `hx-headers:inherited` and element `hx-status`; Pyganini docs use bare inherited headers and full-feature JS enumerates global `noSwap` rules | `adapt` visible example markup and docs in the stable-HTMX child; no framework policy |
| Reload-only content paths | Goldr commit `f2422d8` adds `--reload-path`; Pyganini full-feature loop watches Python and built assets, with manual browser refresh | `adapt` to application-owned example tooling in the authoring child |
| Go toolchain, Go modernization, module consolidation, Go process cancellation fix | Go-specific changed code and metadata | `reject` direct port; preserve Python 3.13/3.14, uv, and existing process ownership |
| Branding, README reorganization, and regenerated products | Source/documentation-only delta outside the capabilities above | No additional feature gap; update affected Pyganini usage during each child |

Existing adaptations remain intact: Starlette dispatch, FastAPI hosting, sync
Jinja, generated URLs, mounted routes, navigation, inspection, CSRF, SSE wire
helpers, fingerprinted assets, and bounded client islands. A full Goldr dev
proxy, templ compiler, Go module layout, and Windows supervisor are not required
to preserve the accepted Python application workflows. Native Windows example
supervision remains an explicit deferral, not a passing check.

## 3. Children and Dependencies

| Track | Child | Status | Durable docs and full-feature impact | Next evidence |
| --- | --- | --- | --- | --- |
| Content pages and generated miss integration | [Content pages](2026-10-03-content-pages.md) | Implemented; owner accepted | New content user/architecture guides; rendering, errors, middleware, composition, packaging, and parity updates; full-feature content bootstrap | Complete within this goal |
| Stable HTMX 4 | [Stable HTMX 4](2026-10-03-stable-htmx4.md) | Implemented; owner accepted | Browser, HTMX, CSRF, SSE, and island docs; full-feature visible status rules and stable assets | Complete within this goal |
| Content authoring and reload-only development | [Content authoring](2026-10-03-content-authoring.md) | Implemented; owner accepted | Development guide and app-owned shared example tooling; full-feature and content example browser refresh | Complete within this goal |

Content and stable HTMX can be implemented sequentially under their own accepted
children. The authoring child depends on the content API and stable browser
baseline. Accepting one child does not accept another. No agent delegation is
required or authorized by these documents.

## 4. Planning Evidence

Read-only checks passed in the pinned Goldr checkout:

```text
go test ./content
# From examples/content_pages:
go test . -run '^TestExampleHandler$' -count=1
```

A disposable, no-project uv probe on CPython 3.14.7 used `markdown-it-py==4.2.0`,
`mdit-py-plugins==0.6.1`, and `linkify-it-py==2.2.0`. It confirmed tables,
disabled checked task inputs, strikethrough, HTTP(S)/www/email autolinks, headings
with document-local duplicate IDs, ID reset between renders, raw inline HTML,
and an explicitly allowed trusted `javascript:` link. A second isolated probe
on CPython 3.13.15 confirmed parser imports, heading IDs, task lists, and www and
email links. These are dependency feasibility checks, not Pyganini tests.

Primary dependency references:

- [markdown-it-py configuration](https://markdown-it-py.readthedocs.io/en/latest/using.html)
- [Plugin APIs](https://mdit-py-plugins.readthedocs.io/en/stable/index.html)
- [markdown-it-py 4.2.0](https://pypi.org/project/markdown-it-py/4.2.0/)
- [mdit-py-plugins 0.6.1](https://pypi.org/project/mdit-py-plugins/0.6.1/)
- [linkify-it-py 2.2.0](https://pypi.org/project/linkify-it-py/2.2.0/)

One smaller parser candidate was inspected but not selected: its built-in URL
plugin covers HTTP(S) URLs, while the selected linkifier also proves www and
email autolinks without a new Pyganini link parser. Only the selected parser
family belongs to the proposed dependency boundary.

## 5. Goal Checklist

- [x] Pin current checkouts and inspect the complete Goldr baseline delta.
- [x] Classify discovered gaps and preserve existing Python ownership decisions.
- [x] Run disposable Markdown feasibility checks on both supported Python lines.
- [x] Prepare separate child contracts and perform their handoff-quality pass.
- [x] Owner accepts the content child.
- [x] Owner accepts the stable-HTMX child.
- [x] Owner accepts the dependent authoring child.
- [x] Complete implementation under the accepted content child and pass its
  required checks.
- [x] Complete implementation under the accepted stable-HTMX child and pass its
  required checks.
- [x] Complete implementation under the accepted authoring child and pass its
  required checks.
- [x] Refresh `docs/arch/parity.md` to the pinned Goldr target with actual evidence,
  retained adaptations/deferrals, and no stale claim of feature qualification.
- [x] Run candidate-specific installed-distribution, typing, host, browser, and
  Python 3.13/3.14 checks for the combined change; identify any unavailable gate.
- [x] Independently review implementation, address confirmed findings, and
  confirm remediation through a focused independent re-review.
- [x] Record owner acceptance of the completed scope and close the goal.

Do not move an incomplete or failed item to complete to satisfy the goal. A
failed probe, an API conflict, an unsupported dependency combination, or a scope
change returns the affected child to design review before implementation resumes.

## 6. Candidate Closeout

All three implementation slices are present with current-state docs and
command-generated examples. The independent review confirmed three content
defects; the owner authorized fixes on 2026-10-03. Focused regressions first
reproduced the failures. The corrected content/source suite passes 47 cases,
with 51 content/source/typing cases on Python 3.13 and all 334 scoped
content/render/dispatch cases on Python 3.14. Root tests pass 1105 cases with one
skip on each supported Python line. Both affected examples pass their quality,
generated/asset, and browser suites on both lines.

The review's fake-child test limitation is also corrected: a signal guard first
reproduced the unmocked cleanup attempt. All 43 supervisor cases pass on each
line after mocking fake cleanup; dedicated real-process tests still exercise
actual shutdown. No supervisor production behavior changed.

The corrected combined qualification report is
`/tmp/pyganini-review-fixes-qualification.0sowu7xk/evidence/report.json`. All
fifteen Q001-Q080 scenarios pass with `PASS_TO_PERFORMANCE_QUALIFICATION`,
including installed distributions, typing, hosts, stable-runtime browser flows,
and both islands. Initial and final candidate identity match; every scenario
reports removed temporary products and clean process-group cleanup. Environment
cleanup and infrastructure errors are null. All 31 entries in `SHA256SUMS`
verify.

The qualified candidate has base HEAD
`8231ddd4537ef88b3a33dae3829ba584271aa283` and combined SHA-256
`c6d6d9c206d45bfa07d4d19022e138a67d6623d7f4771e279ba2406e2b8d5c44`.
This report binds the corrected implementation before evidence-only closeout
updates to the four child/umbrella specs. No production source, tests, examples,
generated output, or dependencies changed afterward. The report's disposable
mirror commit is not a commit in the owner checkout. The original bundle at
`/tmp/pyganini-parity-qualification.Kt7F42/evidence` covers the pre-review
candidate and is superseded for current qualification. Interrupted or invalid
attempts receive no passing credit.

The owner supplied a single-agent focused independent re-review on 2026-10-03.
All three content findings and the fake-child test correction are independently
confirmed resolved. No remaining actionable finding or new regression was
confirmed within remediation scope. Independent evidence includes 334 scoped
cases on Python 3.14, 51 content/source/typing cases on Python 3.13, and all 43
supervisor cases plus 18 additional probes on each line. Scoped Ruff, framework
mypy/Pyright, and diff checks pass. The reviewer verifies all 31 checksums and
the 84-file untracked inventory, with only four declared spec closeout
differences and no candidate/index drift during review.

This was a focused remediation review. Full qualification, browser workflows,
and distribution installation remain author evidence, not independent reruns.
Native Windows remains unsupported, remote Linux CI is unrun, and no performance
qualification or release credit is claimed.

The owner accepted the concrete completed scope on 2026-10-03. This records
human acceptance separately from author validation and independent review.
The parity goal is complete at the pinned target. Performance qualification,
commit, push, publication, release, and deployment remain separate gates; the
report verdict grants no release authority.
