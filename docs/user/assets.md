# Assets

Pyganini can fingerprint final browser-ready files that an application places in
`assets/build`. It does not compile, bundle, optimize, upload, serve, or inject
asset references. The application owns its asset tool, static host, cache
policy, deployment, and browser refresh policy.

## Fixed layout

An enabled application has this application-owned and Pyganini-managed boundary:

```text
assets/
  __init__.py                  application package marker
  src/                         optional application-owned source tree
  build/                       final browser-ready input
  dist/                        Pyganini-managed fingerprinted copies
  .pyganini/assets.json           Pyganini-managed cleanup state
  pyganini_assets_gen.py          Pyganini-generated typed lookup module
```

Pyganini reads only `assets/build`. The build tree may contain CSS, JavaScript,
images, fonts, or vendored files. Every entry below it must be a contained,
regular, non-symlinked file or directory. Names are portable ASCII POSIX paths.
The application must create `assets/__init__.py`; Pyganini never creates it.

Each file is copied to the same logical parent below `assets/dist` with the
first eight lowercase hexadecimal characters of its SHA-256 digest inserted
before its final suffix:

```text
assets/build/app.css              -> assets/dist/app.<hash>.css
assets/build/vendor/htmx.min.js  -> assets/dist/vendor/htmx.min.<hash>.js
```

## Commands

Run these commands from the application root or pass `--app-root`:

```text
pyganini assets dist [--app-root PATH]
pyganini assets check [--app-root PATH]
pyganini assets list [--app-root PATH] [--json]
pyganini assets clean [--app-root PATH]
```

`dist` scans and validates all input, writes changed dist files, writes the
generated lookup module, removes only stale files named by valid prior state,
and writes state last. It uses descriptor-anchored, no-follow traversal and
same-directory staged replacement, preserves identical file modification
times, and never clobbers a destination that appeared after ownership was
checked. If a previous run wrote a byte-correct fingerprinted file before its
state update failed, a rerun may adopt that exact file without replacing it;
conflicting unrecorded files remain application-owned. `check` is read-only and
reports every reachable missing, stale, obsolete-managed, or state difference.
`list` builds its table or `pyganini.assets.v1` JSON entirely from `assets/build`;
it does not inspect managed output. `clean` removes stale state-owned files and
updates state without rebuilding current dist files or the generated module.

Success output for `dist` and `clean` is:

```text
Pyganini asset state: written=<n> unchanged=<n> removed=<n>.
```

Expected asset failures return `1` without a traceback. `PYGANINI020
asset-filesystem` covers boundaries, inputs, state syntax, and containment.
`PYGANINI021 asset-state` covers reachable check differences. `PYGANINI022
asset-write` covers staging, replacement, cleanup, and partial mutation.

## Generated lookup

Application code imports the generated module after `pyganini assets dist`:

```python
from assets import pyganini_assets_gen as assets

stylesheet = assets.path("app.css", base_path=request.scope.get("root_path", ""))
maybe_script = assets.lookup("app.js")
all_assets = assets.manifest()
```

The module exports `Asset`, `path`, `lookup`, and `manifest`. It performs no
filesystem access at import or request time. `path()` raises `KeyError` for an
unknown logical name; `lookup()` returns `None`. Both functions validate and
quote a decoded mount prefix using the same base-path contract as generated
route URLs. `manifest()` returns a new dictionary and frozen `Asset` values.

## Application composition

Mount `assets/dist` through the host application. A Starlette application can
use `StaticFiles(directory=...)` at `/assets`; a FastAPI application can mount
the same application-owned surface under its own prefix. If the application
adds immutable caching, apply it only to fingerprinted asset responses:

```text
Cache-Control: public, max-age=31536000, immutable
```

Pages, fragments, actions, errors, CSRF responses, and SSE responses retain
their application-owned cache behavior. Unrecorded files below `assets/dist`
are preserved by Pyganini and remain application-owned, so a host that permits
such files needs a path-aware cache policy.

Keep the cache wrapper independent of Pyganini. The application composition layer
may read the generated manifest and inject a plain collection of fingerprinted
relative paths into that wrapper; the wrapper itself must not import the
generated module or any Pyganini module.

## Normal generation and development

When `assets/build` exists, normal `pyganini generate` and `pyganini check` include
the asset projection after validating the route state. Assets remain outside
the `app/_pyganini` route plan. Without `assets/build` and without managed-output
indicators, normal command output is unchanged. A missing build tree with
managed indicators is a fail-closed configuration error.

An application-owned watcher may watch `assets/build` together with its source
files. It must ignore `assets/dist`, `assets/.pyganini`, and the generated lookup
module, prepare generation and check while the current server remains alive,
and replace the server only after both succeed. Browser refresh remains manual.

CI should run the application asset tool first, then `pyganini assets check`, then
normal `pyganini generate` and `pyganini check`, followed by host and browser tests.

## Limits

Pyganini does not own `assets/src`, Tailwind, Vite, esbuild, Sass, TypeScript,
bundling, minification, source maps, image or font processing, npm, a static
server, cache middleware, CDN policy, integrity metadata, compression, a
watcher command, or browser reload. Input and output directories, URL prefix,
hash algorithm, and hash length are fixed in this v0 contract.

The installed `pyganini.browser` helper is not an `assets/build` input or an
`assets/dist` projection. Applications mount its fixed helper app separately
and choose its stable URL and `no-cache` revalidation policy. Application
assets, including a vendored HTMX extension, continue through the fingerprinted
immutable asset workflow above.
