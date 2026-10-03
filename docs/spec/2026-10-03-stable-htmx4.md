# Spec: Stable HTMX 4 Parity

Status: implemented
Created: 2026-10-03
Updated: 2026-10-03

## 1. Authority and Dependencies

This is a child of the [Goldr parity umbrella](2026-10-03-goldr-parity-umbrella.md).
The owner accepted this child on 2026-10-03 and authorized implementation within
its scope. Commit, push, publication, release, and deployment remain separate
approvals. `AGENTS.md` and [Spec Authoring Policy](README.md) remain binding. Target Goldr head is
`eb8ed60a34922cca988f81f2990ced85e72a81c3`; commit `9e40d85` supplies the stable
HTMX delta. Pyganini planning head is `8231ddd4537ef88b3a33dae3829ba584271aa283`.
The content child is independent; authoring browser qualification uses this child.

The owner accepted the completed implementation on 2026-10-03 after independent
review, remediation confirmation, and corrected-candidate qualification.

## 2. Goal

Pyganini's optional browser helpers, supported examples, and documentation work
with HTMX 4.0.0. Named SSE swaps, inspector redraw, CSRF headers, form validation,
and bounded island cleanup are proved against the actual stable runtime.

## 3. Non-Goals

No compatibility adapter for beta6/HTMX 2, new client runtime, generated JS,
automatic script injection, framework swap/CSRF policy, client state, new
dependency in the Python runtime, content implementation, or dev proxy. Do not
upgrade unrelated React/Svelte/Vite/Playwright packages or change route behavior.

## 4. Background and Evidence

Current Pyganini sources use `htmx_before_sse_message` and inspector events
`htmx:afterSwap`/`htmx:afterSettle`. Its full-feature, chat, kit, React, and Svelte
examples vendor 4.0.0-beta6. Some browser tests manually invoke the old hook and
assert that beta version. CSRF docs show a shared bare `hx-headers` attribute;
the full-feature script enumerates global `noSwap` exclusions.

Goldr now uses `htmx_sse_before_message`, `htmx:after:swap`,
`htmx:after:settle`, `hx-headers:inherited`, and visible `hx-status` rules.
This is a baseline gap, not a claim that the earlier supported beta contract was
independently reviewed or that the new candidate is qualified.

## 5. Desired Behavior

- Vendor the exact official `htmx.org@4.0.0` core distribution in existing
  application-owned build inputs. Vendor its matching `hx-sse` extension only
  in examples already using SSE. Preserve license/notices and record version,
  source URL, and SHA-256 for the vendored bytes. No runtime CDN requirement.
- Change the existing `pyganini-sse-event` extension to its stable
  `htmx_sse_before_message` hook. Keep its named-event matching, multiple swap
  declarations, target/swap/settle options, inherited root-path URLs, and explicit
  opt-in contract. No old-hook alias.
- Change inspector redraw listeners to the stable swap/settle event names.
  Keep initial load, resize, DOM observation, and existing overlay selection.
  Assert actual event delivery after an HTMX swap, not only a synthetic event.
- Shared CSRF headers use visible `hx-headers:inherited`. Element-local headers
  remain element-local. Existing signed-token, duplicate-evidence, validation,
  and app-owned middleware rules are unchanged.
- Remove full-feature's enumerated global `noSwap` policy. On applicable
  triggering forms/buttons declare `hx-status:422="swap:outerHTML"`,
  `hx-status:4xx="swap:none"`, and `hx-status:5xx="swap:none"`; preserve each
  control's existing target and successful swap mode. An exact 422 rule wins
  over its wildcard. Normal 204/304 suppression remains the stable runtime's
  default. No framework policy is installed.
- Update examples' bounded island HTMX lifecycle hooks if the stable runtime
  requires it. Keep one cleanup before replacement and one mount after insertion,
  with no remounting retained islands or duplicating event subscriptions.

## 6. Locked Decisions and Invariants

Disposition is `preserve` browser capabilities, `adapt` stable wire/event names
and visible markup. `pyganini.browser` retains its public helper paths and API;
changed bytes receive their computed ETags through the current resource owner.
HTMX stays visible in Jinja. Host mounting, cache policy, CSP, authentication,
assets, user validation, and browser state remain application-owned.

The public helper names are already Python adaptations of Goldr's helper names;
there is no new terminology, root export, or renderer/dependency surface.
The baseline is exactly 4.0.0, not an unbounded latest release. Third-party
vendored assets are source inputs; Pyganini-generated outputs are regenerated.

## 7. Rules and Failure Modes

Missing versioned source distributions, a changed npm integrity value, mismatched
extension/core versions, or a runtime hook absent from the pinned stable package
blocks that phase. Inspect the owning primary package before revising the child.
Do not make stable tests pass by exposing both old and new hook names, injecting
test-only hooks, replacing actual HTMX with a mock, or ignoring failing requests.

Start any testable regression fix with a focused failing test against the actual
stable boundary. ASGI tests can prove statuses and headers, but not that a browser
swaps SSE content, inherits headers, redraws markers, or cleans up islands.
Browser infrastructure failures leave browser qualification open.

## 8. Existing Patterns to Reuse

Reuse `src/pyganini/browser`, its fixed-resource/ETag/type tests, the full-feature
Chromium fixture and same-origin request guard, chat's SSE tests, generated asset
projection, and `scripts/check-client-islands.sh`. Use official versioned npm
files and current first-party source; do not hand-edit minified upstream assets.

## 9. Implementation Touchpoints and Agent Containment

Expected framework/test paths: `src/pyganini/browser/*.js`,
`src/pyganini/browser/__init__.py` only if stable resource handling requires it,
`tests/test_browser.py`, `tests/test_browser_typing.py`, and
`tests/test_package_install.py` for installed helper evidence.

Example paths: `examples/{full_feature,chat,kit_routes,react_island,svelte_island}`
application-owned Jinja, JS and TS island code, tests, README/notices, and
`assets/build/vendor/`; full-feature `assets/build/app.js` and relevant route
templates. All affected `assets/dist/`, `assets/.pyganini/assets.json`,
`assets/pyganini_assets_gen.py`, and `app/_pyganini/` are command-owned products.
New `THIRD_PARTY_NOTICES.md` files in server examples may document vendored bytes.
Chat's `pyproject.toml` and uv-managed `uv.lock` may add the same test-only
Playwright version as full-feature for its new browser proof; no runtime
dependency or unrelated dependency version changes are permitted.

Doc paths: `README.md`, `docs/user/{browser,template-inspection,htmx,csrf,sse,
client-islands}.md`, `docs/arch/{browser,htmx-async-forms,csrf,parity}.md`,
this child and umbrella. `scripts/check-client-islands.sh` may change only when
its existing checks need the accepted stable baseline. Known touchpoints are
not an exhaustive deny list inside the accepted behavior.

Forbidden: Goldr writes, source dispatch/render/graph changes, runtime Python
dependencies, unrelated npm/uv upgrades, development-loop work, content work,
release versions/tags/workflow, commits, staging, push, publication, deployment.
Stop if a new public API, global browser policy, or beta compatibility layer is
needed; revise and reaccept the child.

## 10. Proposed Design

Update the two existing helper resources directly. Update authored example
templates/scripts and official vendor source bytes, then run the asset writer.
Preserve the existing fixed-resource application and generated asset lookup.
No wrapper or compatibility abstraction is necessary.

## 11. Implementation Plan

- [x] Verify official 4.0.0 core/extension files and record exact source hashes and
  notices before replacing vendor input.
- [x] Add focused stable-runtime failing evidence for SSE named-event handling
  and inspector redraw, then change the helper hook/listener names.
- [x] Update consumer/unit/distribution expectations, preserving resource
  caching, GET/HEAD/304, explicit mounting, and public typing.
- [x] Replace beta asset inputs, shared CSRF markup, and full-feature global
  status policy; regenerate outputs and update usage docs in this phase.
- [x] Prove inherited CSRF token delivery/rotation, 422 swap, 4xx/5xx suppression,
  204/304 no-swap, named SSE filtering/swaps, and real inspector redraw in Chromium.
- [x] Prove chat's actual stable SSE path and both client islands' mount/cleanup
  behavior without a CDN or lifecycle duplication.
- [x] Run required root/example checks on both Python lines, record evidence,
  remove stale beta references.
- [x] Obtain implementation-owner acceptance.

## 12. Acceptance Criteria

The checklist is complete. Stable HTMX is loaded from local assets in browser
evidence; no old-hook or beta6 compatibility branch remains. Source tests and
real browser flows agree on named SSE, overlay updates, visible CSRF/status
policy, and island lifecycle. Generated products match authored inputs, durable
docs describe current behavior, and all required checks have actual results.

## 13. Validation Commands

Planning uses the docs-only exception. Future implementation, from root:

```text
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 pytest -q tests/test_browser.py tests/test_browser_typing.py tests/test_package_install.py
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy src/pyganini
uv run --locked --python 3.14 pyright src/pyganini
uv run --locked --python 3.14 pytest
uv sync --locked --all-groups --python 3.13
uv run --locked --python 3.13 pytest
bash scripts/check-client-islands.sh
git diff --check
```

If the content extra already exists, add `--all-extras` to root sync/run commands
as required by that accepted child. From each changed example root, run its
locked sync, `pyganini assets dist`, `pyganini generate`, assets/generated checks,
Ruff, mypy, Pyright, and pytest commands from its README on 3.13 and 3.14.
Full-feature browser commands, from its root:

```text
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked --python 3.14 playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=.playwright uv run --locked --python 3.14 pytest -q tests/test_browser.py
```

Add a focused real-HTMX SSE Chromium test to chat if absent; use the existing
full-feature fixture style and the same browser commands in chat's project.
Its Playwright dependency is test-only and must be uv-locked. These commands
are not reported as run during planning. Stop every server/browser started.

## 14. Documentation and Example Updates

Update named public guides and example README/notices together with behavior.
Document stable event hooks, inherited CSRF headers, and visible status rules.
Full-feature and islands remain ordinary downstream apps. CLI help, generated
starter, and Python package APIs receive no new feature. Installed helper bytes
and hashes change normally, with no hard-coded ETag values in runtime code.

## 15. Cleanup and Legacy Removal

Remove beta6 version claims, old hook/listener expectations, and the enumerated
global status policy. Remove stale state-owned fingerprints through asset
commands. A rollback restores matching vendor inputs, helper hooks, templates,
and generated outputs together; do not ship mixed stable/beta halves. Fold
implemented behavior into durable docs before later spec cleanup.

## 16. Open Questions

None required for implementation. Exact official vendor file integrity is an
implementation verification gate, not permission to select another baseline.
Unexpected stable-runtime differences require a spec revision. Content,
automatic refresh, broader Windows support, and release remain separately owned.

## 17. Implementation Evidence

The candidate uses official npm `htmx.org@4.0.0`, with archive integrity verified
against the versioned registry metadata. Core SHA-256 is
`e484d9171a9db30a39c8f16e3d709d4137f3211c659f8e6125816635033d593f`;
SSE extension SHA-256 is
`8a834680c4000a9034d79228872372a92e140c810a075cb6d4a76690dfc13085`.
Notices preserve the upstream license. Server inputs and both Vite public inputs
use those exact bytes; asset commands replaced obsolete fingerprints.

Real stable-runtime failure preceded the SSE hook correction. Source helper
and inspector tests also failed for the old hook/event names before correction.
Full-feature real Chromium now proves local 4.0.0, named SSE swaps, actual stable
swap/settle delivery, inherited CSRF token delivery and rotation, 422 redisplay,
403/500 suppression, and unchanged 204/304 behavior. Chat proves real SSE and
422 under a host prefix. Both React and Svelte browser lifecycle checks pass.
Island checks can select a free local port without touching an unrelated host.

Ruff, both type checkers, generated/asset checks, and tests pass on Python
3.13.15 and 3.14.7. Full-feature has 95 passing tests on each line, including the
subsequent authoring proof; Chat has 27, kit routes 9, navigation 47, and each
island 18 plus its real-browser lifecycle proof. Root tests pass 1095 with one
skip on each line, including installed helper byte/hash checks. Source typing
reports zero diagnostics. Logs remain outside the checkout under
`/tmp/pyganini-parity-*`; interrupted or invalid runs receive no passing credit.
Combined qualification also passes all fifteen scenarios; the fresh report at
`/tmp/pyganini-parity-qualification.Kt7F42/evidence/report.json` includes the
full-feature browser and both island workflows. Its candidate identity and
cleanup checks pass and every checksum verifies. The umbrella records the
evidence-only closeout boundary. Final owner acceptance follows the corrected
candidate qualification below.

The post-review content fixes and fake-child test correction are covered by a
fresh combined report at
`/tmp/pyganini-review-fixes-qualification.0sowu7xk/evidence/report.json`. All
fifteen scenarios pass, including stable-runtime browser and island checks;
candidate identity, cleanup, and all checksums verify. Root tests now pass 1105
with one skip on each Python line. The umbrella records the corrected candidate
identity and evidence-only closeout boundary. No stable helper or vendor bytes
changed during remediation.

The owner accepted the completed implementation on 2026-10-03. Commit, push,
publication, release, and deployment remain separate approvals.
