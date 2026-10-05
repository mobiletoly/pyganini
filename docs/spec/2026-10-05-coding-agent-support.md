# Spec: Coding-agent application support

Status: implemented
Created: 2026-10-05
Updated: 2026-10-05

## 1. Authority and Dependencies

The owner explicitly requested implementation of the complete proposed plan in
this session. That instruction accepts this child, which records the same
decisions. Root `AGENTS.md` and the spec-authoring policy remain binding. The
completed 2026-10-03 parity umbrella remains historical and unchanged.

Starting clean Pyganini head: `c002c84d31c9949573782bb4f8165294d7ad43d8`.
Read-only Goldr target: `eb8ed60a34922cca988f81f2990ced85e72a81c3`.
No agent delegation or independent agent trials are authorized. Commit, push,
publication, remote installation, release, and installed-agent changes remain
separate gates.

## 2. Goal

Provide a self-contained, installable Pyganini App skill that lets coding agents
create, edit, debug, and review downstream applications without either framework
checkout. Provide Codex and Claude Code installation documentation and reusable
application rules, matching Goldr's application-agent capability.

## 3. Non-Goals

No runtime, generated-output, CLI, dependency, host, framework version, or
example behavior changes. No hooks, MCP servers, skill executable helpers,
starter machinery, framework-development skill, or global agent installation.
No model/provider calls or independent agent evaluations. Browser interaction
is unchanged; ASGI requests suffice for the documented HTML/header examples.

## 4. Background and Evidence

Goldr owns `docs/skills/goldr`, its root marketplace, and
`docs/user/coding-agents.md`. Pyganini has contributor rules and current user
guides but none of those application-agent products. Its contributor policy
must not become a downstream application's instruction contract.

Goldr's ten reference topics are adapted to Python/Jinja/ASGI. Goldr App maps to
Pyganini App, with the skill/plugin named `pyganini-app`. No competing public
framework terminology is introduced. The installed Claude Code 2.1.193 supports
the root single-skill layout and strict manifest validation. Goldr's plugin
omits a version and fails strict validation; this package includes `0.1.0`.

## 5. Desired Behavior

`docs/skills/pyganini-app/` is the only canonical skill package. It contains
`SKILL.md`, `agents/openai.yaml`, `.claude-plugin/plugin.json`, and ten references:

- `project-setup.md`
- `routes.md`
- `navigation.md`
- `shared-kit-routes.md`
- `htmx-fragments-actions.md`
- `forms-csrf-dependencies.md`
- `assets-dev-sse.md`
- `content-pages.md`
- `template-inspection.md`
- `validation.md`

The entrypoint selects references by task instead of loading every reference.
Local reference links resolve within the installed package. Setup includes a
copyable minimal page, layout, dynamic route, and Starlette host. The HTMX
reference includes a form action and layout-free fragment. References teach
existing contracts rather than introduce new interfaces.

## 6. Locked Decisions and Invariants

- Skill/plugin name: `pyganini-app`; display name: `Pyganini App`.
- Automatic selection stays enabled through the default invocation policy.
- Plugin version: `0.1.0`, independent of Pyganini `0.2.0`.
- Marketplace name: `pyganini`; plugin source is `git-subdir`, URL
  `mobiletoly/pyganini`, path `docs/skills/pyganini-app`.
- The Codex installer URL ends in `tree/main/docs/skills/pyganini-app`.
- Claude commands use `marketplace add mobiletoly/pyganini --sparse
  .claude-plugin` and `plugin install pyganini-app@pyganini`.
- Keep Python packages, explicit declarations, generated URL helpers, sync Jinja,
  visible HTMX, application-owned policy, and generated-file ownership.
- Use uv for new-app examples, preserve existing app tooling, and retain
  installer-neutral consumer ownership. No invented init/dev commands.
- Optional features are conditional. Public-contract changes require updates
  to affected references. All new content is ASCII.

## 7. Rules and Failure Modes

Package validation fails for malformed metadata, inconsistent identity/source,
missing references, links escaping the installed package, or stale documented
app examples. App validation must expose stale output before regeneration and
verify changed route helpers and dispatch afterward. Missing external validators
are reported as unrun gates, never passes. A runtime defect is reported for
separate scope; this child does not authorize its repair. Network/dependency
failure does not authorize cloning framework source into a downstream app.

## 8. Existing Patterns to Reuse

Reuse Goldr's distribution shape, current Pyganini user guides and public source,
`tests/test_documentation.py` link/index checks, existing pytest subprocess and
ASGI integration patterns, and skill-creator metadata/validation tools. Do not
copy Go or templ contracts. Use the current generated `app/_pyganini` package.

## 9. Implementation Touchpoints and Agent Containment

Expected changes:

- this child
- `.claude-plugin/marketplace.json`
- `docs/skills/pyganini-app/**`
- `docs/user/coding-agents.md`
- `README.md`, `docs/user/README.md`, `docs/arch/parity.md`
- `tests/test_documentation.py`, `tests/test_coding_agent_package.py`

No edits to `src/`, examples, dependencies/lockfiles, global agent configuration,
Goldr, or the completed umbrella. Temporary isolated app products and validator
environments stay outside the repository. Necessary in-scope documentation and
focused tests follow root policy; explicit exclusions remain binding.

## 10. Proposed Design

Instruction-only skill with task references, quoted Codex UI strings, no tool
dependencies, and versioned Claude JSON metadata. The user guide contains the
installation commands, invocation examples, application `AGENTS.md` snippet,
and maintenance rule. README and user-index entries match. The parity ledger
adds one `adapt` row whose evidence owners are the skill and guide.

Package tests use existing dependencies to check identities, declared source
location, and all local Markdown links after copying the package. Small smoke
tests materialize the actual fenced example files from references into a
temporary app, run the installed CLI in subprocesses, and send ASGI requests in
a fresh subprocess so generated imports cannot leak between app generations.
They do not snapshot prose or assert reference headings.

## 11. Implementation Plan

- [x] Complete the ten-point handoff review before implementation.
- [x] Add the canonical skill, ten self-contained references, and agent metadata.
- [x] Add the root marketplace and strict-validatable plugin manifest.
- [x] Add user setup/application rules, matching indexes, and parity evidence.
- [x] Add package/link/index checks and isolated documented-app smoke checks.
- [x] Run focused validation, skill validation, and both strict Claude validators.
- [x] Run Python 3.14 quality/full tests and Python 3.13 full tests.
- [x] Review the final diff, record exact evidence, and mark implemented only
  after every required gate passes.

## 12. Acceptance Criteria

Both agent distributions point to the same self-contained skill. The guide is
discoverable and its application rules preserve existing project instructions.
Local manifests pass strict validation. Documented apps render their page and
dynamic route, return correct HTML/headers without a page layout for a form
fragment, and detect/regenerate a renamed route with updated helper/dispatch.
The complete copied package resolves its local references. Existing quality and
compatibility checks pass. Hosted installation is not claimed from local proof.

## 13. Validation Commands

Run from the repository root:

```text
uv sync --locked --all-groups --all-extras --python 3.14
uv run --locked --all-extras --python 3.14 pytest -q tests/test_documentation.py tests/test_coding_agent_package.py
uv run --no-project --python 3.14 --with pyyaml python /Users/pochkin/.codex/skills/.system/skill-creator/scripts/quick_validate.py docs/skills/pyganini-app
claude plugin validate --strict docs/skills/pyganini-app
claude plugin validate --strict .claude-plugin/marketplace.json
uv run --locked --all-extras --python 3.14 ruff format --check .
uv run --locked --all-extras --python 3.14 ruff check .
uv run --locked --all-extras --python 3.14 mypy src/pyganini
uv run --locked --all-extras --python 3.14 pyright src/pyganini
uv run --locked --all-extras --python 3.14 pytest
uv sync --locked --all-groups --all-extras --python 3.13
uv run --locked --all-extras --python 3.13 pytest
git diff --check
```

The no-project PyYAML environment is solely for the external skill-creator tool;
no project dependency changes. Tests invoke `python -m pyganini generate`,
`check`, `routes list --json`, and `routes explain` inside isolated apps.

## 14. Documentation and Example Updates

The new guide, skill references, matching README indexes, and parity ledger own
the durable behavior. `examples/full_feature` and other examples remain current
and need no behavior changes; references use their established contracts. There
is no generated starter, CLI help, framework typing, or docstring impact.

## 15. Cleanup and Legacy Removal

No obsolete implementation exists. Leave no scaffold placeholders, duplicate
skill copies, temporary apps, installed global skills, or running servers. All
generated smoke products are temporary. Do not modify historical specifications.

## 16. Open Questions

None. Package checks and app smoke tests were selected by the owner during
planning. Publication and remote installation remain separate gates.

## Handoff Review and Implementation Evidence

The implementer completed the ten-point handoff review before implementation.
This child stands alone, fixes package identity and behavior, separates global
installation/publication gates, names reuse and containment, supplies observable
acceptance and exact commands, requires temporary-product cleanup, records the
Goldr `adapt` disposition, and states durable-doc and example impact. No unresolved
decision or invented framework contract is needed to implement it.

Candidate evidence (local uncommitted changes on the starting head above):

- `uv sync --locked --all-groups --all-extras --python 3.14`: passed.
- `uv run --locked --all-extras --python 3.14 pytest -q tests/test_documentation.py tests/test_coding_agent_package.py`:
  7 passed. The four new tests verify metadata/source identity, copied-package
  reference closure, documented page/dynamic route and read-only stale/refactor
  behavior, and documented HTMX form HTML/escaping/header/422/layout behavior.
- `uv run --no-project --python 3.14 --with pyyaml python /Users/pochkin/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py docs/skills/pyganini-app --interface 'display_name=Pyganini App' --interface 'short_description=Create and maintain Pyganini applications' --interface 'default_prompt=Use $pyganini-app to create or make a focused change in this Pyganini application, including routes, Jinja layouts, HTMX workflows, and validation.'`:
  generated the UI metadata with the bundled skill-creator tool.
- `uv run --no-project --python 3.14 --with pyyaml python /Users/pochkin/.codex/skills/.system/skill-creator/scripts/quick_validate.py docs/skills/pyganini-app`:
  passed.
- `claude plugin validate --strict docs/skills/pyganini-app` and
  `claude plugin validate --strict .claude-plugin/marketplace.json`: both passed
  on Claude Code 2.1.193.
- `uv run --locked --all-extras --python 3.14 ruff format --check .`:
  passed, 428 files already formatted. Its first run found one unformatted
  fenced example; `uv run --locked --all-extras --python 3.14 ruff format docs/skills/pyganini-app/references/forms-csrf-dependencies.md`
  corrected that example before the passing rerun.
- `uv run --locked --all-extras --python 3.14 ruff check .`: passed.
- `uv run --locked --all-extras --python 3.14 mypy src/pyganini`: passed,
  no issues in 25 source files.
- `uv run --locked --all-extras --python 3.14 pyright src/pyganini`: passed,
  zero errors/warnings/informations. The pinned tool also prints a separate
  newer-version advisory; its version was not changed.
- `uv run --locked --all-extras --python 3.14 pytest`: 1109 passed,
  1 skipped in 107.15 seconds on CPython 3.14.7. The existing asset test skips
  its case-sensitive-name proof because the host filesystem is case-insensitive.
- `uv sync --locked --all-groups --all-extras --python 3.13`: passed,
  CPython 3.13.15.

- `uv run --locked --all-extras --python 3.13 pytest`: 1109 passed,
  1 skipped in 112.01 seconds on CPython 3.13.15, with the same existing
  case-insensitive-filesystem skip. All four new tests passed on both releases.
- `uv sync --locked --all-groups --all-extras --python 3.14`: restored the
  contributor environment after compatibility validation.
- `git diff --check`: passed. Final review covered all 21 changed/new files,
  checked new files and added lines for ASCII, checked new-file whitespace,
  and confirmed the child containment. Goldr stayed clean at the pinned head.

The package, metadata, references, guide, indexes, and parity row were reviewed
against current public source and user docs. Public API/dependency/source/example
behavior and the completed umbrella are unchanged. The handoff review remains
complete after these evidence-only checklist/status updates.

Remote installation, publication, release, and independent agent trials did not
run and are outside this child's completion gate. No application server was
started. No commit, push, installed-agent change, or model/provider call occurred.
