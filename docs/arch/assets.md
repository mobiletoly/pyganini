# Asset projection architecture

Pyganini asset support is a separate managed product boundary. It does not reuse
the complete `app/_pyganini` route writer because an asset-only operation must not
interpret missing route artifacts as obsolete output.

## Ownership and flow

The private `_assets.py` owner projects:

```text
selected ProjectPaths
  -> assets/build scan
  -> immutable content projection
  -> assets/dist copies
  -> assets/pyganini_assets_gen.py
  -> assets/.pyganini/assets.json
```

`_cli.py` owns argparse, diagnostics, output, and coordination. The generated
asset module imports only the standard library and `pyganini._url_binding`. Pyganini
runtime code never imports application-generated assets. Starlette, FastAPI,
static serving, cache headers, and deployment remain host ownership.

## Projection

The scanner anchors the real `assets` and `assets/build` directory objects once.
Those identities remain held through comparison or mutation, including normal
generation's route work. Traversal and reads are descriptor-relative and
no-follow. POSIX reads use `O_NOFOLLOW`, `O_NONBLOCK`, and an opened-file
identity check; Windows retains held parent handles and reparse-point rejection.
The scanner validates the application-owned `assets/__init__.py` and every
descendant without following symlinks. It reads complete regular-file bytes
before mutation, computes SHA-256, keeps the first eight lowercase hexadecimal
characters, preserves logical POSIX parents, and sorts logical names. Portable
name validation and case-normalized logical and dist collision checks happen
before output mutation.

The generated Python module contains a frozen slotted `Asset` dataclass and a
private ordered manifest. Its URL values are unbound `/assets/...` paths.
`path()` and `lookup()` normalize a decoded base path through the shared URL
segment contract; `manifest()` returns a new dictionary. There is no import-time
filesystem access, request-time hash, Jinja global, facade, or static server.

## State and cleanup

`assets/.pyganini/assets.json` is deterministic ASCII JSON with schema
`pyganini.assets-state.v1`, ordered `schema` and `managed` keys, sorted rows, and
logical, dist, and hash row keys. Before cleanup Pyganini validates the complete
state, including schema, duplicate rows, normalized contained dist paths, and
eight-character lowercase hashes. Only prior state rows absent from the current
projection are cleanup candidates. Unrecorded files below `assets/dist` remain
untouched.

The write sequence is:

1. select and validate the project and fixed asset boundaries;
2. scan and read all build input;
3. validate collisions and render all current products in memory;
4. validate prior state and cleanup targets;
5. stage changed current dist files and the generated module in destination
   directories;
6. replace current files through same-directory staged files;
7. remove validated stale state-owned files and newly empty managed parents;
8. replace state last; and
9. report counts after the operation closes.

Each staged file retains its opened destination-parent object through install,
discard, and parent synchronization. A replacement parent or asset/build root
therefore fails closed instead of redirecting work. Each file replacement is
atomic and synchronized, but the operation is not a cross-file transaction.
Previously absent destinations use an atomic no-clobber install. Recorded
destination identities are captured during ownership validation, carried into
the final replacement check, and never refreshed from a later occupant. A
partial failure records completed mutations and directs
the developer to rerun `pyganini assets dist` followed by `pyganini assets check`.
When a changed fingerprinted output was completed but state was not, the rerun
accepts that output only when its bytes exactly match the new projection.
Conflicting unrecorded files are still rejected and never overwritten or
deleted. Staging files are removed when safe. `check` never calls the mutation
path.

## Command coordination

Asset-only commands select and validate the application package but do no route
graph or `app/_pyganini` work. Normal generation prepares the complete asset
projection before route mutation, writes the existing complete route plan, and
then writes assets. Normal check compares route state before asset state. An
application with no build tree and no managed indicators keeps the existing
four route-generated products and command output byte-for-byte. A missing build
tree with a managed indicator fails before normal generation mutation.

The full-feature example owns `StaticFiles`, immutable response headers, and
the application watcher. The watcher observes `app` Python files outside
`app/_pyganini` and all non-directory changes below `assets/build`; it ignores
asset output and keeps the active server alive while generation and check run.

`pyganini.browser` is a separate installed-package resource boundary. Its fixed
allowlist and stable ETag-serving app do not read `assets/build`, write
`assets/dist`, import generated asset lookup data, or provide application
static serving. The application may compose both mounts under its chosen host
and cache policies.
