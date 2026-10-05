---
name: pyganini-app
description: Create, edit, debug, or review downstream applications using the Pyganini Python web framework. Use for application setup, filesystem routes, Jinja layouts, HTMX fragments and actions, shared route kits, content pages, assets, and validation. Framework implementation follows the framework repository's own policy.
---

# Pyganini App Development

Use this skill in an application repository that uses Pyganini, or when adding
Pyganini to an application. Pyganini is server-first, HTML-first, HTMX-native,
filesystem-routed, and Python-native.

This package is self-contained. Do not assume the Pyganini or Goldr framework
repository is available, clone either as a setup workaround, or edit framework
source unless the user requests framework development. Follow the application's
own instructions and existing tooling. The skill does not authorize unrelated
configuration changes, publication, deployment, or messages to others.

## Application workflow

1. Inspect the app's dependencies, instructions, host bootstrap, scripts, tests,
   and `app/routes` tree. The empty `[tool.pyganini]` table in `pyproject.toml`
   marks its root. Use `--app-root` when running outside that root.
2. For a new app or missing setup, read the project-setup reference. For an
   existing app, inspect ownership with `pyganini routes list` before route
   changes; the command reads source without importing handlers.
3. Edit app-owned declarations, handlers, and Jinja first. Keep related render
   behavior in its route package. Read only the task references needed below.
4. Generate Pyganini-owned files rather than editing them. Inspect paths and
   helpers after refactors, run focused checks, and check relevant host/browser
   behavior when the change requires it. Stop any server started for the task.

Prefer the app's wrapper commands. For a uv-managed app, the ordinary loop is:

```bash
uv run --locked pyganini generate
uv run --locked pyganini check
uv run --locked pyganini routes list
uv run --locked pytest
```

## References by task

- New app, dependencies, minimal page/layout/host:
  [Project setup](references/project-setup.md).
- Route packages, declarations, generated URLs, middleware, errors:
  [Routes](references/routes.md).
- Breadcrumbs, semantic Back, destinations, request-local trails:
  [Navigation](references/navigation.md).
- Shared implementations, owner-specific state, selected mounted subtrees:
  [Shared kit routes](references/shared-kit-routes.md).
- Visible HTMX, fragments, actions, response headers:
  [HTMX fragments and actions](references/htmx-fragments-actions.md).
- Form/upload parsing, captured request data, CSRF, app dependencies:
  [Forms, CSRF, and dependencies](references/forms-csrf-dependencies.md).
- Fingerprinted assets, app-owned development, SSE and browser helpers:
  [Assets, development, and SSE](references/assets-dev-sse.md).
- Trusted HTML/Markdown and generated-router miss handling:
  [Content pages](references/content-pages.md).
- Source inspection, render comments, optional development overlay:
  [Template inspection](references/template-inspection.md).
- Final checks, typing, stale state, host and browser evidence:
  [Validation](references/validation.md).

## Ownership and invariants

- Use regular Python packages and explicit `Route` declarations. Do not add
  runtime registration, a second router, call-stack root inference, or FastAPI
  dependency injection to Pyganini handlers.
- Keep `hx-*` visible in `.jinja`. Use generated `.path` values for represented
  internal routes, including response headers. Bind the trusted ASGI
  `root_path` explicitly; do not infer it from proxy headers.
- Finish application I/O in handlers before synchronous Jinja rendering. Async
  handlers run on the ASGI loop; sync handlers run in workers. Do not call async
  Request methods from a sync handler or create another event loop.
- Applications own the ASGI server, host, middleware, auth, sessions, persistence,
  validation, dependency wiring, static serving, cache policy, and deployment.
- No SPA routing, hydration, virtual DOM, or framework-owned client state.
  Existing bounded client islands remain application-owned.
- Do not hand-edit or add app code below `app/_pyganini/`, or patch
  `assets/pyganini_assets_gen.py`, `assets/.pyganini/assets.json`, or managed
  fingerprinted files below `assets/dist/`.

If current declarations differ from generated output, inspect the source and
regenerate before changing runtime behavior. If an app's conventions or installed
version conflict with this guidance, identify that mismatch and use its actual
supported contract; do not invent compatibility shims or rewrite unrelated code.
