# Spec: Application-Owned Content Authoring Loop

Status: implemented
Created: 2026-10-03
Updated: 2026-10-03

## 1. Authority and Dependencies

Child of the [Goldr parity umbrella](2026-10-03-goldr-parity-umbrella.md), subject
to `AGENTS.md` and [Spec Authoring Policy](README.md). The owner accepted this
child and the [content](2026-10-03-content-pages.md) contract on 2026-10-03 and
authorized implementation within their scopes. Commit, push, publication,
release, and deployment remain separate approvals. Implement it after that child
and [stable HTMX](2026-10-03-stable-htmx4.md) supply the required examples and
browser baseline. No source work is authorized by the umbrella.

The owner accepted the completed implementation on 2026-10-03 after independent
review, remediation confirmation, and corrected-candidate qualification.

## 2. Goal

Authors can save external content and see a browser refresh while the example
server keeps its PID and generated route products. The full-feature and
standalone content examples show one documented application-owned development
loop, including new nested pages and repair after invalid content saves.

## 3. Non-Goals

No public `pyganini dev` command, proxy, framework watcher/client/reload endpoint,
automatic production script injection, content cache, transactional publishing,
SPA state, new runtime dependency, compiler/bundler, or Windows supervision.
Packaged immutable content still requires normal rebuild/restart. Do not expand
reload-only watching into route Python, generated output, or asset source builds.

## 4. Background and Evidence

Goldr's `--reload-path` observes external runtime-readable paths without route
generation or application restart. Pyganini's full-feature `dev.py` already
supervises a process group, watches application Python and final built assets,
runs generate/check before replacement, and retains the running server if
preparation fails. Jinja and external content can observe request-time edits;
the missing capability is application-owned browser notification.

Disposition is `adapt`: preserve the author workflow using a Python application
supervisor and explicit host/template wiring. No Goldr proxy, Go compiler,
framework CLI, or templ machinery is copied. The existing POSIX supervision
boundary and native Windows deferral remain explicit.

## 5. Desired Behavior

### Example tooling

Extract the shared parts of full-feature `dev.py` into
`examples/dev_support.py`. Two small example-local `dev.py` entrypoints supply
their explicit root and Uvicorn factory. This is repository example tooling,
not Pyganini's installed public API. The two real consumers justify extraction;
keep the existing configuration/process functions, without a plugin/facade layer.
Wrappers load this exact file by a path derived from their own `__file__`, using
ordinary `importlib` machinery; no call-stack root inference or recursive lookup.

Keep `--host` and `--port`. Add repeatable `--reload-path PATH`, relative to the
selected example root, plus a default external `content` path in these two
examples. Repeated identical roots are deduplicated. A configured path must
exist as an ordinary file/directory. Reject symlinks/reparse points, special
files, nested/overlapping reload roots, and overlap with app routes/generated
output or asset build/dist roots. A deleted directory root is terminal; a
deleted exact-file root may be recreated and remains an observed edit. Invalid
configuration fails before generation/server startup.

Observe an exact-file root through its parent, filtering notifications to that
file; unrelated sibling edits are not accepted changes. These backend watch
paths do not expand the accepted reload surface. Directory roots are recursive.

Watch application Python and final built assets with the existing preparation
and restart behavior. Observe existing `.jinja` template edits and configured
external content as refresh-only events. A refresh-only batch writes a reload
revision; it runs no generate/check/assets command and sends no process signal.
A mixed batch first completes normal preparation/restart, then publishes one
revision. Failed preparation retains the server and publishes no revision.
Watch-generated files, revision files, caches, and temporary editor files must
not cause feedback loops. Ignore `__pycache__`, `.pyc`, `.pyo`, and names ending
in `~` or beginning with `.#`; regular content saves remain visible.

### Explicit development host and HTML wiring

The supervisor owns a temporary directory with one revision file and exports
its absolute path to the child through `PYGANINI_EXAMPLE_RELOAD_FILE`. Its
contents are a fresh session UUID plus a monotonic integer, for example
`<uuid>:0`. Increment by atomic replacement after an accepted change batch.
This is app-owned process coordination, not a framework config key or API.

Only each example's explicit development factory mounts
`/_example/reload` before the root Pyganini mount. It reads revisions in a worker,
polls at 250 ms, emits an initial named `reload` SSE event containing the current
revision and then only changed revisions, with comment heartbeats every 15
seconds. Emit `Cache-Control: no-cache`, cleanly close on request disconnect,
and retain no global subscriber registry. Do not perform blocking file reads in
the event loop. Missing/unreadable coordination state ends the stream with
application-owned logging; it does not affect production routes.

An explicit application-owned `assets/build/dev-reload.js` is fingerprinted
normally. The development root layout alone renders its script with a
`data-events-url` bound through the existing trusted ASGI base path. The script
opens one EventSource, remembers the first revision without reloading, and calls
`location.reload()` only after a different revision. It retains that revision
across reconnects so a restart/disconnected edit is observed, and closes on
page exit. A new browser page establishes a new baseline. Session UUIDs prevent
revision reuse after restarting the supervisor. Do not change HTMX or preserve
application client state across a full reload.

Production factories expose neither endpoint nor reload script, even if the
environment variable exists. No framework/browser package resource is added.
App-owned script/endpoint paths need no generated URL helper; prefix binding
must work under a host mount. Development is intentionally opt-in through the
named factories and commands, with the existing loopback default.

## 6. Locked Decisions and Invariants

Content and Jinja reads stay request-time. The watcher only notifies browsers;
it neither parses content nor invents a last-known-good result. Invalid or
incomplete live content shows the existing app-owned error response until
repaired. Content additions need both page files, without a handler/template per
page. Layout/middleware/Python additions still require generation and restart.

The shared example helper may use only stdlib and the examples' existing
`watchfiles` dependency. Host SSE uses existing Starlette/Uvicorn/Pyganini SSE
helpers. Browser EventSource is native. No new framework public name, runtime
dependency, dev lifecycle hook, or client registry is introduced.

## 7. Rules and Failure Modes

Bound all process readiness and shutdown waits. Preserve the full-feature
SIGINT/SIGTERM/SIGKILL escalation, descendant reaping, initial preparation
failure, dead-child recovery, and cleanup evidence. Remove task-owned revision
directories on every normal/error shutdown and stop when cleanup cannot be
proved. A failed revision write is terminal and reports its application-owned
phase; do not report a refresh that was never published.

No content change should alter generated product bytes, mtime, or child PID.
An invalid live save may yield a terminal content error; repairing it must
refresh into the valid page without a restart. Do not loosen content validation
or suppress the error to make the authoring workflow look successful.

Browser infrastructure unavailability leaves browser qualification open.
Never use an arbitrary fixed sleep as proof of refresh, server readiness, or
process cleanup; wait for observable revision/request/DOM/process facts with
bounded deadlines.

## 8. Existing Patterns to Reuse

Reuse full-feature `dev.py`, `tests/test_dev.py`, explicit development app
factory, app-owned SSE endpoint style, root layout mapping, fingerprinted asset
paths, Chromium fixture, and same-origin network guard. The content example
supplies its own factory and explicit root while sharing only developer tooling.

## 9. Implementation Touchpoints and Agent Containment

Tool owners: new `examples/dev_support.py`; full-feature and content example
`dev.py`, pyproject/uv lock, README, `tests/test_dev.py`,
`tests/test_browser.py`, `app/main.py`, an app-owned `app/development.py` when
needed for the explicit SSE endpoint, root layout mapping/templates, and
`assets/build/dev-reload.js`. Generated assets/lookup/state and `app/_pyganini`
are command-owned. Add test-only Playwright/watchfiles dependencies to the
content example, matching full-feature's existing versions and uv workflow.
`.github/workflows/ci.yml` may add these two examples' development-browser
commands on the existing Linux/Python matrix, without changing release gates.

Docs: `README.md`, new `docs/user/development.md`,
`docs/user/{README,content-pages,assets}.md`,
`docs/arch/{application-composition,parity}.md`, this child and umbrella.
Expected paths are not a deny list for necessary in-scope app/test/docs work.

Forbidden: `src/pyganini/`, new framework CLI/browser resources, unrelated
examples, content API/validation changes, route/asset semantics changes,
performance/release machinery, Goldr writes, commits, staging, push, publication,
deployment. Stop before Windows support, remote/proxy operation, new dependencies,
framework ownership, or changed content contract; revise and reaccept the child.

## 10. Proposed Design

One app-owned shared supervisor selects restart versus refresh events. One
temporary revision file bridges its lifetime with restarted child processes.
Each explicit development factory mounts its own read-only SSE endpoint and
visibly includes an app-owned browser script. The normal app factory knows
nothing about development notification. This avoids another listener, proxy,
network control API, shared subscribers, or runtime framework lifecycle.

## 11. Implementation Plan

- [x] Preserve existing supervisor tests while extracting their actual shared
  owner and adding the second explicit wrapper; keep process cleanup semantics.
- [x] Add focused tests for reload configuration, disjoint path sets, deletion,
  ignores, restart/refresh/mixed classification, and atomic revision publication.
- [x] Add success and failure tests proving refresh-only batches invoke no
  generator or restart, failed preparation emits no refresh, and revision write
  failure terminates with cleanup.
- [x] Add explicit development-only SSE endpoint, revision polling/offload,
  disconnect handling, visible script, and mount-prefix behavior; prove production
  has no endpoint/script even with the environment variable present.
- [x] Prove real browser edit, new nested page, invalid-save error, repair,
  reconnect, Python restart, and Jinja refresh with observable evidence.
- [x] Document commands and external/packaged differences in the same phase;
  regenerate changed products with normal commands.
- [x] Run both examples' checks, browser proof, and POSIX process cleanup checks;
  record unsupported Windows qualification accurately.
- [x] Obtain implementation-owner acceptance.

## 12. Acceptance Criteria

Every checklist item is verifiable. Browser refresh works for both consumers,
including nested new content and recovery. Refresh-only evidence proves stable
PID and unchanged generated bytes/mtime. Python/asset changes still obey
preparation/restart gates. Prefix URLs work, initial connections do not loop,
reconnects observe missed revisions, production remains opt-out, and all child
processes, streams, browser contexts, and revision directories are cleaned up.

## 13. Validation Commands

Docs-only planning uses handoff review and `git diff --check`. Future checks,
from both `examples/full_feature` and `examples/content_pages`, using each line
3.13 and 3.14 (commands show 3.14):

```text
uv lock
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 pyganini assets dist
uv run --locked --python 3.14 pyganini generate
uv run --locked --python 3.14 pyganini check
uv run --locked --python 3.14 pyganini assets check
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy app dev.py ../dev_support.py tests
uv run --locked --python 3.14 pyright app dev.py ../dev_support.py tests
uv run --locked --python 3.14 pytest -q
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked --python 3.14 playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked --python 3.14 pytest -q tests/test_browser.py
```

Dogfood both wrappers with
`uv run --locked --python 3.14 python dev.py --reload-path content` on Darwin or
Linux. Record DOM revision, child PID, generated hashes/mtime, and clean shutdown.
Use temporary content copies in browser tests. Run root Ruff (including the new
shared tool) and root pytest with all extras, from the repository root:

```text
uv sync --locked --all-groups --all-extras --python 3.14
uv run --locked --all-extras --python 3.14 ruff format --check .
uv run --locked --all-extras --python 3.14 ruff check .
uv run --locked --all-extras --python 3.14 pytest
uv sync --locked --all-groups --all-extras --python 3.13
uv run --locked --all-extras --python 3.13 pytest
git diff --check
```

Report unavailable platform/browser checks; owner acceptance remains separate
from author validation.

## 14. Documentation and Example Updates

Document one ordinary app-owned loop, refresh-only versus restart changes,
explicit development factories, resource lifetimes, packaged-content limits,
invalid-save recovery, mounted URLs, and shutdown. Full-feature manual-refresh
instructions are replaced only after the new loop is proved. Installation,
CLI help, generated starter, and Pyganini package docstrings gain no dev API.

## 15. Cleanup and Legacy Removal

Remove duplicated supervisor implementation and stale manual-only claims from
the two consumers. Preserve ordinary production bootstrap, content live reads,
and independent application packaging. Rollback removes shared tooling and
development wiring together and restores the previous full-feature loop; asset
commands remove stale managed files. Keep temporary revisions outside the
repository and fold implemented behavior into durable docs before spec cleanup.

## 16. Open Questions

None implementer-owned. The shared example tool, revision-file/SSE bridge,
production opt-out, default content roots, and POSIX support are accepted locked
decisions. Windows supervision and a public framework dev
command are deferred; no parity credit is claimed for them.

## 17. Implementation Evidence

The actual shared supervisor retains the original bounded POSIX process-group
and descendant cleanup tests. Its focused suite has 43 passing cases. Additional
real-browser proof gives 44 passing supervisor/browser cases on each supported
Python line after the final generated-asset ignore checks. Both type checkers
pass the shared supervisor, wrappers, app sources, browser test helper, and tests.

Full-feature and standalone content Chromium proofs use temporary application
copies and actual wrappers. They prove edited content, a newly added nested
Markdown page, invalid metadata producing 500, repair refreshing automatically,
a disconnected edit observed on reconnect, Jinja refresh, and Python restart.
Content/Jinja saves retain PID and exact generated bytes/mtime. Shutdown proves
children are gone and the coordination directory is removed. Initial SSE
connections establish a baseline without a reload loop; production endpoint/
script absence and mounted public URLs have focused tests. Revision reads run
in workers; disconnect and missing-state stream closure are tested.

The complete full-feature suite passes 95 cases and standalone content passes
7 cases on Python 3.13.15 and 3.14.7. New guide, indexes, example commands, CI,
and command-generated products are current. This Darwin run supplies POSIX
cleanup evidence; native Windows is unsupported and is not qualified. Linux CI
is configured, but no remote CI result is claimed.

Combined qualification passes all fifteen scenarios with matching candidate
identity, clean cleanup, and all checksum entries verified. The report at
`/tmp/pyganini-parity-qualification.Kt7F42/evidence/report.json` includes the
full-feature authoring browser proof. The umbrella records the evidence-only
closeout boundary. Final owner acceptance is recorded after remediation below.

## 18. Review Test-Harness Remediation

The supplied independent review noted an inherited fake-child test could signal
pytest's own process group. A focused signal guard first fails by observing a
real cleanup attempt for that fake PID. The corrected unit test mocks cleanup,
asserts the exited child is cleaned up once, and retains the guard against real
signals. Dedicated real-process shutdown/escalation/descendant tests still own
actual cleanup evidence. No supervisor production behavior changes.

This change is within the accepted test/cleanup contract. All 43 supervisor
tests pass on Python 3.13/3.14 after the change, including dedicated real-process
cleanup tests. Ruff, mypy, and Pyright pass. Fresh combined qualification passes
all fifteen scenarios in
`/tmp/pyganini-review-fixes-qualification.0sowu7xk/evidence/report.json`, including
all full-feature unit/browser checks, matching candidate identity, clean
cleanup, and verified checksums. The umbrella records the corrected candidate
hash and evidence-only closeout boundary. The earlier report binds the earlier
candidate.

The owner supplied a single-agent focused independent re-review on 2026-10-03.
It confirms the fake-child correction resolved, with repeated-polling and
signal-guard probes passing. All 43 supervisor cases and 18 additional probes
pass on each Python line in the reviewer's disposable complete copy. Dedicated
real-process cleanup tests remain intact and production supervisor bytes are
unchanged. The review reports no remaining actionable finding or new confirmed
regression within remediation scope. The owner accepted the completed
implementation on 2026-10-03. Commit, push, publication, release, and deployment
remain separate approvals.
