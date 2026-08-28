# Pyganini qualification probes

This standalone uv project qualifies one identified Pyganini worktree through its
built distribution and public commands. It creates a byte-verified disposable
mirror, runs an explicit scenario matrix, and writes raw evidence outside the
repository.

The package, fixture, scenario IDs, JSON schema, and helper interfaces belong
to repository tooling. Pyganini applications must not import them or treat them as
a compatibility promise.

## Setup and checks

Run the locked project checks from this directory:

```text
uv lock --check
uv sync --locked --python 3.14
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy qualification_probes tests
uv run --locked --python 3.14 pyright qualification_probes tests
uv run --locked --python 3.14 pytest -q
uv sync --locked --python 3.13
uv run --locked --python 3.13 pytest -q
```

uv owns `uv.lock`. Do not edit it by hand.

## Q010 root typing contract

Q010 runs root validation from the byte-verified disposable candidate mirror.
Its strict source typing lane is:

```text
uv run --locked --python 3.14 mypy src/pyganini
uv run --locked --python 3.14 pyright src/pyganini
```

Its public-consumer typing lane is:

```text
uv run --locked --python 3.14 pytest -q tests/test_csrf_typing.py tests/test_sse_typing.py tests/test_assets.py::test_generated_asset_consumers_are_checked_by_both_type_checkers
```

The focused pytest owners require valid CSRF, SSE, and generated-asset
consumers to pass under mypy and Pyright. Invalid consumers must fail for their
intended public-signature errors; unresolved imports, missing generated
modules, unknown-type cascades, or checker setup failures do not count as
rejection proof. The asset owner creates its generated module through the
production asset path in a disposable application before either checker runs.

Q010 also retains Ruff, package installation, wheel, and source-distribution
checks. It aggregates independent command failures before reporting a finding.
Runtime-negative CSRF and SSE modules remain full-pytest evidence and are not
direct zero-diagnostic typing inputs.

## Q042 and Q043 phase contracts

Q042 deletes the declared `app/routes/users/page.jinja` after generating the
fixture and snapshotting every file below `app/_pyganini`. Installed-wheel
`pyganini generate`, `pyganini check`, and `pyganini routes list --json` must each exit
1 with `PYGANINI009 route-filesystem`, the exact template path, and `cannot
inspect required template file`. They must emit neither route JSON nor a
Python traceback, and the generated path, size, and SHA-256 snapshot must stay
unchanged after each command. Q042 does not issue a request: request-time
`PYGANINI015 render-template` remains the separate contract for transitive Jinja
loads, custom loaders, and other failures that static route evidence cannot
decide.

Q043 appends the module-level `RuntimeError("qualification import failure")`
sentinel after generation. Installed-wheel `pyganini check` and source-only
`pyganini routes list --json` must pass without importing its handler module or
executing the sentinel. Each command runs its installed-wheel entrypoint under
a task-local Python audit hook that records the handler import attempt even if
command code catches the resulting exception and exits 0. A fresh fixture
interpreter then imports `app._pyganini.asgi` and observes the private startup
wrapper without importing `pyganini._dispatch` from the qualification script.
The concrete wrapper must be `DispatchError` with `PYGANINI012 route-import`,
path `app/routes/users/route.py`, and message `cannot import route module
'app.routes.users.route'`. Its direct cause must be the concrete application
`RuntimeError` with the sentinel message, and that cause traceback must retain
the handler path and sentinel line. Generated products remain unchanged around
the complete path. Q044 separately owns request-time application exceptions,
the generated-route error callback, and post-response-start behavior.

## Run qualification

Choose a new absolute output path outside the Pyganini repository:

```text
PYGANINI_QUAL_OUTPUT=$(mktemp -d /tmp/pyganini-qualification-output.XXXXXX)
uv run --locked --python 3.14 python -B -m qualification_probes \
  --pyganini-root /absolute/path/to/pyganini \
  --output "$PYGANINI_QUAL_OUTPUT/evidence"
```

The default interpreter order is 3.14 followed by 3.13. Repeat `--python` to
make that selection explicit. Repeat `--scenario` to run a focused set. The
runner adds required scenario dependencies and Q080 in matrix order. Final
identity, process, and cleanup gates therefore apply to every focused run.
The `-B` flag prevents the live qualification package import from writing
ignored bytecode before candidate capture. Worker commands also use `-B`, and
the inherited environment disables bytecode writes for their Python children.

```text
uv run --locked --python 3.14 python -B -m qualification_probes \
  --pyganini-root /absolute/path/to/pyganini \
  --output "$PYGANINI_QUAL_OUTPUT/refactor" \
  --scenario Q030 --scenario Q031 --scenario Q080
```

The command rejects staged or unmerged candidate state and rechecks both at
the closing identity gate. It accepts unstaged tracked and non-ignored
untracked files, hashes them, and copies them into the verified mirror.
Qualification commands do not run from the live checkout.
If an enumerated path disappears, or a tracked path changes between missing and
present during capture, the runner rejects the moving candidate instead of
omitting the file. Missing tracked paths remain explicit manifest records, and
mirror construction rechecks the complete tracked, untracked, and missing path
state before and after copying. It also rechecks bytes, file identity, and the
full permission mode. Device, inode, modification-time identity, and permission
mode must still match the captured manifest, so an identical atomic replacement,
mode-only change, or missing-path reappearance cannot produce an incomplete
verified mirror. Scenario workers and fixture inputs load from this mirror, not
from the live probe checkout.

## Evidence and exit status

The final directory contains `report.json`, `SHA256SUMS`, and byte-preserved
stdout and stderr files below `raw/`. JSON metadata replaces disposable,
repository, and home paths with placeholders. Raw streams remain unchanged.
Q001 associates the distribution build command, timing, status, and streams in
one record. Both candidate identities name the fixed disposable Git commit.
Q080 records final identity agreement, process audit results, and removal of
the task-owned temporary root after scenario execution.
The runner captures uv and interpreter metadata while that root exists. It
executes no cache-using metadata command after cleanup. Every metadata command
has a fixed deadline, bounded output cleanup, and the same durable ownership
tracker as scenario commands. If any scenario, identity Git, build, or metadata
command detects and terminates an owned survivor after the command exits, the
run records incomplete infrastructure evidence even when termination succeeds
and the command itself returned zero.

The writer keeps evidence atomic. A failed raw-stream write marks its staging
directory incomplete, preserves that named directory for recovery, and blocks
finalization. The runner does not promote a partial staging tree to the final
output path. It still audits and cleans task-owned processes, removes the
temporary root, and recaptures final candidate identity before returning the
blocked verdict. Finalization also refuses to publish evidence if the
qualification temporary root exists.

Verify the evidence from its directory:

```text
shasum -a 256 -c SHA256SUMS
```

The command returns:

- `0` for `PASS_TO_PERFORMANCE_QUALIFICATION`;
- `1` for `FINDINGS_REQUIRE_REMEDIATION`; and
- `2` for `BLOCKED_EVIDENCE_INCOMPLETE`.

A product finding records the observed contract mismatch and leaves Pyganini
source unchanged. An infrastructure or evidence failure prevents a candidate
verdict. Q070 treats a failure from the composed client-island script as
incomplete infrastructure evidence because that script combines dependency,
browser, and product checks under one exit status.
Q060 keeps non-browser tests in the product lane and treats its browser pytest
lane as incomplete infrastructure evidence because browser startup and
loopback binding share that command's exit status. Q080 treats dirty or ignored
mirror residue as a cleanup failure, not a product finding.
Q060 and Q070 retain the primary scenario failure when mirror cleanup also
fails, and cleanup residue forces incomplete infrastructure evidence.

## External comparisons and cleanup

The committed runner has no external framework dependency and performs no
external framework checkout. Maintainers refresh Goldr source comparisons
outside the harness and record product decisions in `docs/arch/parity.md`.

Each scenario uses disposable environments, applications, caches, processes,
and browser products. Each scenario receives a separate uv and npm cache below
the temporary root. The runner removes them before final identity capture.
It places command temporary files under the task-owned root, terminates each
process group after command completion or cancellation, and audits that root
for surviving process commands before cleanup.
Command cancellation records the cancelled state, process-group cleanup result,
and any output-communication failure. The runner then completes cleanup and
emits `BLOCKED_EVIDENCE_INCOMPLETE` accounting.
Timeout and cancellation drains stay bounded. The runner records an output-
communication timeout and returns blocked evidence instead of waiting without
a deadline. The final process audit compares process start identities with a
pre-run baseline and checks an inherited opaque qualification marker. It fails
closed on malformed or unreadable same-user process evidence and on empty
environments for attributed processes. Each command starts behind a gate while
the monitor binds its exact root start identity. It attributes new descendants
only through a currently verified parent lineage, never through a numeric PGID,
and retains exact process start identities observed while each command is active.
A later owned command may bind a new generation of a reused PID, but an existing
monitor cannot adopt it.
A detached child remains attributable after reparenting. A known-owned process
remains a cleanup target when its environment is unreadable or malformed. TERM
and KILL target identity-bound processes rather than numeric groups: Linux uses
pidfds and macOS uses precise start identity plus audit-token signaling. The
process-table command uses the same identity-bound KILL path if its own bounded
read times out. PID or PGID reuse therefore cannot redirect a cleanup signal.
The runner repeats the audit after termination, including when initial candidate
capture fails before evidence staging exists and when temporary-root setup or
writer construction fails after allocation. Candidate and disposable-mirror Git
commands use the same bounded command runner and shared lineage tracker. Early
failure explicitly cleans and verifies the temporary root, recaptures final
candidate identity when initial capture succeeded, and re-audits processes.
Detection still blocks the verdict when final termination succeeds. Unmarked
concurrent processes remain outside the result.

Q043 snapshots generated path sets, sizes, and hashes around its expected
startup failure. Q044 applies a separate snapshot and comparison around each
request-failure path, so a later path cannot conceal an earlier mutation. Any
mutation becomes a product finding.
It preserves pre-existing ignored content in the live Pyganini checkout because
the runner never cleans the live repository.
