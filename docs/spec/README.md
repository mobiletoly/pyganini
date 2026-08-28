# Spec Authoring Policy

`docs/spec/` contains short-lived research, planning, and implementation
documents for Pyganini.

Specs guide focused work, keep scope explicit, and define validation and
cleanup. They do not replace durable framework documentation.

Permanent framework behavior belongs in:

- `docs/user/`
- `docs/arch/`
- the repository `README.md` when relevant
- package documentation
- examples
- tests

Do not treat `docs/spec/` as a long-term design archive.

## Document Kinds and Authority

Pyganini uses three kinds of spec documents:

- A research capture records evidence, hypotheses, comparisons, and open
  questions. It grants no implementation authority.
- An umbrella spec defines project direction, work tracks, dependencies, and
  acceptance gates. It authorizes umbrella maintenance, not implementation of
  a track.
- A child spec defines one executable implementation slice. Only a
  handoff-ready child spec that the project owner has accepted authorizes
  implementation.

Use authority in this order:

1. `AGENTS.md` and newer repository instructions.
2. The accepted child spec for the active track.
3. The current umbrella spec.
4. Relevant research captures.

An illustrative API, filename, route tree, or command in research or umbrella
material does not become a Pyganini contract until an accepted child spec says so.

## When a Child Spec Is Required

Write and accept a child spec before implementation when a change affects
architecture, public behavior, or more than one subsystem.

This includes:

- routing or filesystem conventions
- CLI behavior
- generated project structure or generated interfaces
- Starlette or FastAPI integration
- Jinja rendering and layout behavior
- HTMX behavior
- form handling
- development server behavior
- code generation or static analysis
- public APIs or typing contracts
- dependencies or supported Python versions
- breaking changes
- examples or durable documentation

Small local fixes may skip a child spec when they are isolated, obvious, low
risk, and covered by existing tests. Uncertainty about architecture or public
behavior requires a short child spec.

## Lifecycle

Child specs that drive implementation must declare:

```md
Status: draft | accepted | implemented | abandoned
Created: YYYY-MM-DD
Updated: YYYY-MM-DD
```

Optional metadata such as `Owner:` is allowed when it helps coordination.

Status meanings:

- `draft`: the project is shaping the work; implementation is not authorized.
- `accepted`: the owner approved this handoff-ready child for implementation.
- `implemented`: the work is complete, validated, and represented in durable
  docs where required.
- `abandoned`: the project will not pursue this document.

Research captures and umbrella specs may use descriptive status text that
states their non-authorizing role. Acceptance of an umbrella approves its
direction and sequencing, not implementation of any child track.

Delete implemented child specs during cleanup after they stop providing useful
context and durable docs carry the shipped behavior.

## File Naming

Use lowercase ASCII filenames with a creation date:

```text
YYYY-MM-DD-short-slug.md
```

Examples:

```text
2026-08-16-pyganini-foundation-research.md
2026-08-16-pyganini-umbrella.md
2026-08-18-foundation-probes.md
2026-08-24-static-route-graph.md
```

Use `-research` for a research capture and `-umbrella` for an umbrella. Use a
focused behavior or track name for a child spec.

One umbrella may coordinate several dated child specs. Each child must link to
its umbrella, and the umbrella must name the child once its filename exists.
Do not encode an unaccepted sequence into filenames merely because an umbrella
lists a possible delivery order.

`README.md` is the only non-spec file in this directory and does not follow the
spec filename pattern.

## Required Child-Spec Structure

Use this structure for implementation child specs unless the slice has a clear
reason to combine or rename a section:

```md
# Spec: <short title>

Status: draft | accepted | implemented | abandoned
Created: YYYY-MM-DD
Updated: YYYY-MM-DD

## 1. Authority and Dependencies

## 2. Goal

## 3. Non-Goals

## 4. Background and Evidence

## 5. Desired Behavior

## 6. Locked Decisions and Invariants

## 7. Rules and Failure Modes

## 8. Existing Patterns to Reuse

## 9. Implementation Touchpoints and Agent Containment

## 10. Proposed Design

## 11. Implementation Plan

## 12. Acceptance Criteria

## 13. Validation Commands

## 14. Documentation and Example Updates

## 15. Cleanup and Legacy Removal

## 16. Open Questions
```

Keep a child spec as small as its executable slice permits. Split a large child
when it contains separate decision, implementation, or acceptance boundaries.

## Handoff-Ready Child Specs

An accepted child spec must let another engineer implement the slice without
relying on prior discussion, guessing missing decisions, or inventing scope.

The child must include:

- the exact goal and observable outcome
- explicit non-goals
- the supported behavior and rejected behavior
- relevant Goldr parity classified as `preserve`, `adapt`, `defer`, or `reject`
- Python-specific evidence or probe results behind the design
- concrete interfaces, commands, paths, data shapes, and package boundaries
- locked decisions and invariants
- reachable rules and failure modes
- existing helpers, patterns, examples, tests, and docs to reuse
- allowed and forbidden files or directories
- public API, dependency, and refactor constraints
- stop conditions
- phased, verifiable checklist items
- targeted tests or an explicit reason tests are unnecessary
- exact validation commands
- durable docs and `examples/full_feature` impact
- cleanup and legacy-removal requirements
- open questions answered, deferred, or assigned to a later child

Do not mark a child `accepted` while its implementer still needs to decide what
to build. Stop implementation and update the child when new evidence exposes a
missing decision.

Small children may use short sections. Do not omit locked decisions, failure
modes, reuse expectations, or containment when work affects routing,
generation, CLI behavior, development tooling, public APIs, examples, or
multiple packages.

## Umbrella Specs

Umbrella specs may use a lighter structure than child specs. They may track
future work without defining every implementation contract.

An umbrella must make progress inspectable:

- each track has a status
- each track names its child spec after one exists
- each track records durable-doc impact
- each track records `examples/full_feature` impact
- each track records validation state or its next validation action
- dependencies between tracks remain explicit
- parity gaps remain classified as `preserve`, `adapt`, `defer`, or `reject`

The next implementation track needs an accepted child spec. Future tracks may
remain placeholders until they approach implementation.

Do not implement from an umbrella unless the change only maintains umbrella
content.

## Goals and Non-Goals

Goals describe observable outcomes:

- user-visible behavior
- developer workflow
- affected files, packages, or commands
- behavior that must remain unchanged

Every accepted child needs non-goals. Stop and update the child before crossing
one of them.

## Locked Decisions, Reuse, and Containment

Locked decisions and invariants name behavior, boundaries, and architectural
constraints that implementation must preserve. A reviewer must be able to
decide whether the finished work follows them.

Rules and failure modes cover behavior reachable through supported parsers,
APIs, commands, filesystem shapes, generated interfaces, or user input. Do not
require code or tests for unreachable defensive states. A child that retains
defensive handling must name the current entry point that can produce the state
and explain why this slice owns the handling.

Existing patterns to reuse should name the local command, module, helper, test
pattern, example, or documentation style that guides the work. Compare relevant
behavior with the live Goldr implementation, then adapt it through Pyganini's
accepted Python and ASGI boundaries. Do not create a parallel Pyganini system when
an existing Pyganini pattern owns the behavior.

Agent containment must state:

- allowed files or directories
- forbidden files or directories
- public API constraints
- dependency constraints
- refactor constraints
- stop conditions

Any source path, durable doc, generated artifact, configuration file, or script
named by a phase, command, cleanup item, or acceptance criterion must also
appear in implementation touchpoints or containment.

Implementation touchpoints identify expected work. Under an accepted child,
they are not an exhaustive deny list for necessary source, focused tests, or
current-state durable documentation inside the accepted behavior. The
implementer may update an omitted path when the change is required to make the
accepted contract complete, coherent, and verifiable.

Explicit forbidden paths, non-goals, locked boundaries, and later phase gates
remain hard stops. If a child needs exclusive path containment, such as for a
probe, planning-only task, or findings-only review, say that the list is
exclusive and explain the boundary. A missing path by itself is not a reason
to return an otherwise handoff-ready accepted child to draft.

## Architecture Quality Gates

Architecture and package-boundary children must name the durable owner of core
behavior and the contracts it owns.

Do not introduce modules, packages, facades, wrappers, shims, mirrored types,
aliases, or forwarding helpers to hide dependency direction, avoid changing
the real owner, or preserve a weak early structure. A new package must name:

- the durable responsibility it owns
- the packages that should depend on it
- the packages that must not depend on it
- the reason an existing package cannot own the responsibility

A retained temporary bridge or compatibility path needs a named owner, reason,
guardrail, and removal condition before implementation starts.

Prefer explicit v0 contract cleanup when no accepted compatibility requirement
exists. If import cycles or unclear responsibility block clean ownership, stop
and update the child with the available owner options.

Do not create a generic renderer adapter before Pyganini accepts a second
renderer. Do not create a host-framework adapter layer solely for FastAPI while
Starlette's public ASGI interfaces satisfy the accepted integration contract.

## Anti-Pressure Rules

A checklist does not authorize forced validation passes. Failed evidence blocks
the affected item. Update the child with the next design step before changing
downstream behavior to hide the failure.

Do not make a test, example, type checker, or review comment pass with
route-specific strings, path-substring checks, fixture-specific branches,
command-specific exceptions, broad ignores, or one-off generated output unless
the accepted child defines them as product contracts.

Tests, type checkers, examples, and review comments provide validation input.
They do not select implementation behavior. A needed string, path, ignore, or
branch condition requires a named Pyganini contract in the child spec.

Do not weaken Ruff, mypy, Pyright, pytest, generated-state checks, or host
compatibility checks to make an implementation pass unless the child records
the changed quality boundary and the owner accepts it.

## Implementation Plan

Phase non-trivial child specs. Every checklist item must name a concrete code,
test, documentation, validation, or cleanup result that a reviewer can verify.

Good:

```md
- [ ] `pyproject.toml` declares `requires-python = ">=3.13"`.
- [ ] `.python-version` selects the Python 3.14 release line.
- [ ] `tests/test_package_install.py` imports `pyganini` from the built wheel.
- [ ] `uv run pytest tests/test_package_install.py` passes.
- [ ] `docs/user/installation.md` documents installer-neutral consumer setup.
```

Bad:

```md
- [ ] Improve packaging.
- [ ] Make developer experience better.
- [ ] Add tests.
- [ ] Update docs.
```

Place tests and documentation work in the phase that changes their behavior
when practical. Use the final phase for full validation and cleanup, not as the
only place that mentions tests or docs.

Each source phase needs representative success tests and reachable edge-case
tests, or a stated reason tests do not apply. Name relevant edge categories,
such as invalid declarations, missing files, stale generated output,
unsupported route shapes, bad CLI flags, empty results, malformed form input,
cancellation, or host mount prefixes.

Tick a checklist item after code, tests, docs, or validation evidence makes it
verifiable. Do not leave completed work unchecked for later cleanup.

## Drift Control

Do not expand scope without editing and reaccepting the child spec.

During implementation:

- do not add unlisted features
- do not introduce architectural concepts without updating the child
- do not rewrite unrelated code
- do not rename public APIs unless the child requires it
- do not create a second way to express the same route or render behavior
- do not leave obsolete behavior half-supported without an accepted
  compatibility requirement

Update and reaccept the child before continuing when evidence changes scope,
architecture, public behavior, validation, or non-goals.

## Pre-v0 Breaking Changes

Pyganini is pre-v0.

Children may introduce breaking changes that improve architecture, simplicity,
Python-native behavior, inspectability, typing, public API clarity, or
maintenance. Do not preserve weak early conventions unless the child records a
concrete compatibility need.

A child that introduces a breaking change must state:

- the behavior or interface that breaks
- the architectural reason for the new design
- obsolete code, docs, examples, tests, and generated output to remove
- validation that proves the replacement

Pre-v0 freedom supports foundation cleanup. It does not authorize churn without
evidence.

## Project Rules Still Apply

Every spec follows the root `AGENTS.md`.

Do not duplicate the full root policy in a child. Apply these boundaries when
writing one:

- Keep filesystem conventions Python-native and statically inspectable.
- Keep HTMX attributes visible in Jinja templates.
- Use Starlette as the ASGI foundation and FastAPI as a tested host.
- Keep Jinja as the only built-in v0 renderer with async mode disabled.
- Keep ASGI boundaries async while supporting accepted sync and async route
  callables through one public model.
- Keep runtime magic and framework-owned dependency injection out of Pyganini.
- Keep public APIs and dependencies small.
- Treat examples as product surface.

Write `Pyganini` in prose, headings, comments, and user-visible text. Use `Pyganini`
for package names, imports, commands, files, directories, configuration keys,
URLs, HTML attributes, generated markers, and exact diagnostics.

Use plain ASCII unless a concrete product requirement needs Unicode. Avoid em
dashes, smart quotes, decorative bullets, and invisible Unicode whitespace.

## Python, Dependencies, and Public API

A child must call out new dependencies, public APIs, generated APIs, exported
typing surfaces, or toolchain requirements.

It must explain:

- the accepted application problem
- why the standard library and current dependencies do not solve it
- why a small local implementation does not fit
- why Pyganini needs the public surface in this slice
- the maintenance and compatibility cost

Use Python 3.14 for v0 development and support Python 3.13 or newer unless a
later accepted spec changes the policy. Use uv for contributor environments,
dependency locking, and commands. Keep uv out of the consumer runtime contract.

Use public Starlette interfaces. Keep FastAPI a compatibility-test dependency,
not a Pyganini core dependency. Keep Jinja as the direct renderer dependency until
an accepted second use case justifies another renderer.

Public Python interfaces need annotations that mypy and Pyright can check.
Generated public interfaces need stable, inspectable annotations or stubs and
tests that exercise both type checkers. Public modules, classes, functions, and
methods need concise docstrings unless the child explains a narrow exception.

Keep dependencies and public API surface minimal.

## Validation, Docs, and Cleanup

Every accepted child must list exact validation commands. State when a required
command does not exist yet. Do not claim a command passed unless someone ran it
against the candidate under review.

Use focused tests for framework behavior, public APIs, regressions, generated
product surface, and architectural invariants. Prefer the smallest test that
fails when the target behavior breaks.

Avoid broad matrices, large fixture trees, incidental internal assertions, and
large golden files unless they protect an accepted framework contract.

Each child must state its impact on:

- the repository `README.md`
- `docs/user/`
- `docs/arch/`
- `examples/full_feature`
- other examples
- generated starter application
- CLI help
- package documentation and docstrings

Update durable docs in the same implementation slice as behavior. Update
`docs/user/` for supported user behavior. Update `docs/arch/` for framework
architecture, generated-code behavior, or maintainer invariants.

Update `examples/full_feature` when the slice changes applicable public usage,
or record why the example cannot use the behavior yet. A child is incomplete
while durable docs or examples describe stale behavior.

CLI-visible changes need CLI dogfood in their implementation phase.
Browser-visible example changes need browser validation when unit or ASGI tests
cannot prove the behavior.

### Docs-Only Validation Exception

Use this exception only when every changed file is a Markdown file directly
under `docs/spec/`.

For those changes:

- run the handoff-quality pass from this policy when an accepted child changes
- do not require pytest, Ruff, mypy, Pyright, generated-state, packaging,
  FastAPI-host, or browser checks
- run `git diff --check` when a Git worktree exists and the check is useful

The exception does not apply to source, tests, generated files, durable docs,
examples, configuration, or other non-Markdown files. A child that plans future
source work must still list the correct commands for that implementation.

Cleanup belongs to the implementation. Name obsolete code, docs, examples,
compatibility paths, generated files, and tests in the cleanup section.

During v0, durable docs describe the current design. Remove stale artifacts
instead of preserving deprecated behavior or long migration histories unless
the accepted child requires compatibility.

## Handoff Quality Pass

After drafting or editing a child spec, review handoff quality before accepting
it or reporting an accepted-spec edit complete.

Verify:

1. The child stands on its own without chat context.
2. Rules are deterministic and unambiguous.
3. Locked decisions, invariants, and non-goals are explicit.
4. The child names existing patterns to reuse.
5. Touchpoints cover every known path, while explicit exclusions and any
   exclusive containment boundary are clear.
6. Acceptance criteria are concrete and testable.
7. Validation commands are exact, or the docs-only exception applies.
8. Rollback, cleanup, and legacy-removal expectations fit the slice.
9. Relevant Goldr parity has a recorded disposition.
10. Durable docs and `examples/full_feature` impact is explicit.

Remove vague placeholders before acceptance unless the child supplies a default
and a stop condition.

## Definition of Done

A child reaches `implemented` after:

- all required checklist items are complete
- tests were added or updated, or the child explains why none apply
- required validation commands ran, with unavailable commands reported
- durable docs changed with behavior
- applicable examples changed with public usage
- obsolete behavior and documentation were removed
- no parallel obsolete path remains without an accepted reason
- the implementer or reviewer completed the handoff-quality review for any
  child edits
- the child records `Status: implemented`

## Implementation Instructions

An implementation session must:

1. Read `AGENTS.md`, this policy, the umbrella, and the entire accepted child.
2. Confirm that the child satisfies the handoff-quality pass.
3. Identify the active phase and its authority.
4. Stay within containment rules.
5. Reuse the patterns named by the child.
6. Make the smallest coherent change.
7. Preserve unrelated work.
8. Keep filesystem conventions Python-native.
9. Tick checklist items after evidence makes them verifiable.
10. Run listed validation commands when possible.
11. Report commands that did not run.
12. Update durable docs and examples when required.
13. Update omitted source, focused tests, or current-state durable docs when
    necessary to complete the accepted behavior.
14. Stop and request a spec update before violating non-goals, locked
    decisions, invariants, explicit exclusions, or exclusive containment.

Optimize for correctness, coherence, and maintainability.
