# Project, Package, and Generation Architecture

Pyganini is a pure-Python `uv_build` distribution with a `src/pyganini/` package.
CPython 3.14 is the contributor line and CPython 3.13 is the minimum supported
consumer line. A committed uv lock covers both blocking interpreter lines.

## Dependency ownership

Starlette supplies the ASGI foundation, Jinja is the only accepted v0 renderer,
and AnyIO supplies synchronous handler offload with the accepted cancellation
behavior. They are the runtime requirements. FastAPI and the two HTTP clients
belong to compatibility tests. pytest, Ruff, mypy, and Pyright belong to
development groups. uv and `uv_build` are contributor and build tools.
ASGI servers, host frameworks, middleware, lifespan, application dependencies,
and deployment remain application-owned.

The wheel ships only the typed `pyganini` package and distribution metadata. The
source distribution ships the project metadata, README, license, and
`src/pyganini/`. Tests, probes, specs, examples, lockfiles, caches, environments,
and generated applications remain outside both distribution contracts.

## Root typing validation

Strict root source analysis owns `src/pyganini` only:

```text
uv run --locked --python 3.14 mypy src/pyganini
uv run --locked --python 3.14 pyright src/pyganini
```

Both tools run through the CPython 3.14 contributor environment while their
project configuration targets the minimum supported Python 3.13 language and
typing surface. The direct commands do not analyze the complete `tests` tree.
That tree mixes positive consumers, intentional negative consumers,
generated-module consumers, and runtime tests that deliberately pass invalid
values or inspect private seams.

Public consumer typing belongs to focused pytest owners. The CSRF and SSE
typing modules run mypy and Pyright over valid fixtures that must pass and
invalid fixtures that must fail for named public-signature errors. The asset
typing owner first creates a disposable application and writes
`assets/pyganini_assets_gen.py` through the production asset projection; it then
runs both checkers with the application and root `src` directory on the import
path. Missing imports, missing generated modules, unknown-type cascades, and
checker setup failures never count as successful negative evidence.

The focused consumer lane runs under CPython 3.14 in root qualification. The
complete pytest suite, which includes that lane and all other generated and
runtime typing evidence, runs under both CPython 3.14 and CPython 3.13.

## Module direction

The initial internal ownership is:

```text
_config <- _paths <- _route_graph -> _declarations
             ^            |               ^
             |            v               |
             +--- _cli -> _dispatch_generation --+
                          \-> _url_generation --+-> _generation -> _filesystem
                              |
                              v
                          _dispatch -> _render
```

- `_config.py` parses `pyproject.toml` and accepts only an empty
  `[tool.pyganini]` table.
- `_paths.py` selects the physical application root and validates the fixed
  application package paths.
- `_route_graph.py` scans and validates route source and owns the immutable
  internal graph and endpoint derivation.
- `_declarations.py` owns the typed public declaration values and shared
  route-local literal normalization.
- `_navigation.py` owns immutable public navigation values and request-local
  resolution; `_url_binding.py` owns the shared pure path-segment contract.
- `_generation.py` owns the route-neutral artifact value, complete-plan
  validation, comparison, per-file replacement, partial-failure reporting, and
  obsolete cleanup.
- `_filesystem.py` is the generation-only owner of generated-root anchoring,
  entry classification, no-follow traversal, reads, staging, replacement, and
  cleanup.
- `_cli.py` owns `argparse`, exit codes, diagnostic rendering, and coordination.
- `_dispatch_generation.py` projects the validated graph into deterministic
  `app/_pyganini/asgi.py` bytes.
- `_url_generation.py` projects the validated graph into deterministic,
  fully annotated `app/_pyganini/urls.py` bytes and owns URL-helper diagnostics.
- `_inspection.py` projects the validated graph and private URL-helper
  expression facts into immutable endpoint/layout rows and deterministic text
  or JSON bytes; it never reads generated state or creates an artifact.
- `_dispatch.py` owns controlled runtime imports, callable validation and
  invocation, path-priority Starlette routing, render-value selection, response
  validation, and HEAD body suppression.
- `_render.py` owns the public render values, synchronous strict Jinja
  environment, layout composition, render offload, and HTML response creation.
- `_assets.py` owns the fixed final-asset paths, build scan, fingerprint
  projection, generated lookup and cleanup-state bytes, asset comparison, and
  asset-only write lifecycle. It does not import or extend the route graph.

`_generation` receives validated paths and does not parse configuration or
import the graph. `_paths` does not import generation. `pyganini.__init__` exports
`ActionDef`, `Destination`, `FragmentResponse`, `FragmentRouteDef`,
`FragmentRouteResponse`, `KitActionDef`, `KitFragmentRouteDef`, `KitRouteDef`,
`KitRouteMount`, `MountRoute`, `NavTrail`, `NavTrailStep`, `Navigation`,
`NavigationBack`, `NavigationCurrent`, `Page`, `PageMetadata`,
`PageRouteResponse`, `RequestNav`, `RouteDef`, `RouteErrorHandler`, `RouteMeta`,
`RouteNav`, `RouteResponse`, `RouteTarget`, `TemplateInspectionMode`, `action`,
`browser`, `create_environment`, `csrf`, `current_nav_step`, `fragment_route`,
`hx`, `kit_action`, `kit_fragment_route`, `mount_route`, `nav`, `nav_step`,
`route`, `route_kit`, `route_mount`, `sse`, and `to`; graph and generation
values remain internal.

## Separate asset products

Final browser-ready files use a separate managed boundary under `assets/` so
asset-only commands never submit an incomplete `app/_pyganini` generation plan.
When `assets/build` exists, `_assets.py` reads the application-owned final
files, writes fingerprinted copies below `assets/dist`, generates
`assets/pyganini_assets_gen.py`, and records only managed dist paths in
`assets/.pyganini/assets.json`. The asset state is validated before stale cleanup;
unrecorded dist files remain application-owned.

Normal `generate` prepares this complete asset projection before route
mutation, then runs the existing route writer and the asset writer. Normal
`check` compares the route state and asset state without mutation. Applications
without an enabled asset tree do not enter this path, preserving the existing
route-only command behavior. Static serving, cache headers, deployment, and
any compiler or bundler remain host-application responsibilities.

## Root and configuration selection

An explicit root is resolved first and prevents access to unused fallback
inputs. Without one, Pyganini resolves the current working directory and walks its
physical parents through the filesystem anchor. It parses an encountered
`pyproject.toml` before deciding whether to continue, so malformed TOML fails
locally rather than being skipped. The nearest empty `[tool.pyganini]` table wins.

The selected root must contain real directories at `app` and `app/routes` and
regular package markers at `app/__init__.py` and
`app/routes/__init__.py`. An optional `app/mounts` package is used only for
referenced mounted source identities and is subject to the same containment
rules. None may be a symlink or resolve outside the selected root. The
generated root may be absent, but a present boundary cannot redirect traversal.

## Generation plan

The route-neutral plan contains immutable `(PurePosixPath, bytes)` artifacts.
Every path is normalized, POSIX-relative, unique for the filesystem's case
behavior, below `app/_pyganini`, and free of exact or case-normalized parent-file
conflicts. Non-ASCII characters, backslashes, drive forms, Windows device names,
control or Windows-forbidden characters, and components ending in a dot or
space are rejected before mutation.
Generated Python starts with the exact Pyganini ownership comment. Validation and
every later comparison use normalized path order.

The current plan has three generated Python artifacts with exact UTF-8 and LF
bytes:

```python
# Code generated by pyganini; DO NOT EDIT.
"""Generated Pyganini application package."""

# Code generated by pyganini; DO NOT EDIT.
"""Generated Pyganini ASGI routing surface."""

# Code generated by pyganini; DO NOT EDIT.
"""Generated Pyganini URL helper interface."""
```

The generated root also contains `.pyganini-root` with
`pyganini-generated-directory-v1` and a final LF. The marker claims all
non-transient content below the root. Pyganini initializes only an absent or empty
directory and never adopts a non-empty unmarked directory or repairs a corrupt
marker.

## Comparison, replacement, and cleanup

Check mode validates and compares without calling a mutation helper. It reports
all reachable missing, byte-stale, obsolete, and conflicting entries in sorted
order. Python bytecode and `__pycache__` are ignored.

Generation inspects ownership before mutation. Expected output is read only
when its entry is a regular file; directories, symlinks or reparse points,
FIFOs, sockets, and devices are type conflicts. It creates required generated
directories, stages the ownership marker and every changed file in its
destination directory, flushes and calls `os.fsync()`, and uses `os.replace()`
in sorted order only after all staging succeeds. Identical files are not
replaced. Obsolete cleanup starts only after every expected replacement succeeds
and removes entries leaf-first without following symlinks.

On POSIX, generation opens the application and generated directories with
no-follow directory descriptors. Traversal, reads, directory creation,
same-directory staging, replacement, staging cleanup, and obsolete removal are
relative to held descriptors, so a pathname replacement cannot redirect an
operation outside the verified generated-root object. Reads also verify the
opened descriptor is still a regular file and use nonblocking open semantics to
avoid hanging on a raced FIFO.

On Windows, the private backend holds each traversed directory with
`CreateFileW`, directory and open-reparse-point flags, and no delete sharing.
It enumerates explicitly, holds and validates each child directory before
descending, and rejects reparse points before pathname operations. This child
validates the Win32 flag, sharing, rejection, traversal, and handle-lifetime
contract with injected mocks. Windows is not an accepted runtime platform for
this child, so actual Windows execution is not a completion gate; a later
Windows support decision must add execution on Windows before claiming platform
support.

There is no cross-file transaction. A failure before a project mutation is
`PYGANINI007`. A failure after directory creation, parent creation, marker or
artifact replacement, deletion, or another recorded mutation is `PYGANINI008`,
including failures in post-mutation entry or marker verification and filesystem
close. Private staging files are closed and cleaned after staging or replacement
failures; cleanup errors are reported without masking the primary failure. The
journal lists completed mutations in sorted order and preserves every completed
whole-file replacement. Rerunning generation and then check recovers the
expected state.

## Route graph and generator boundaries

Both commands build the static route graph before plan construction. The CLI
combines the route-neutral bootstrap plan, dispatch plan, and URL plan and
submits the complete set to the existing validation, comparison, writer, and
cleanup lifecycle. Dispatch contributes `app/_pyganini/asgi.py` and URL
generation contributes `app/_pyganini/urls.py`; neither adds a root selector,
marker, writer, stale-state implementation, or route model. The URL module
exposes the live `urls` tree and the selection-filtered `mount_urls` binding
catalog from the same graph.

`pyganini routes list` is deliberately outside the generation plan. It selects
paths, builds one graph, builds one shared URL-helper projection, derives and
filters rows, and encodes its complete output in memory before stdout. It adds
no writer, manifest, configuration key, public export, or runtime import.

The generated package bootstrap exports no symbol. `asgi.py` exposes typed
public `create_router(environment=..., error_handler=...)` and annotated public
`router`, both using Starlette `Router`. The optional callback is an
application-owned `RouteErrorHandler`; the default `router` remains
callback-free. `urls.py` exposes only the annotated public `urls` and
`mount_urls` values. Inspection consumes the same graph and helper projection
but contributes no artifact through this plan or writer. See
`docs/arch/route-inspection.md` for its row and output ownership.
