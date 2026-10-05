# Validation

Read this before finalizing a non-trivial app change. Use the app's established
commands and supported Python/dependency versions; the framework repository's
own contribution gates do not automatically become downstream app requirements.

## Ordinary change loop

Generate after changing route ownership/declarations, middleware/layout markers,
template names, or mounted selection. Do not hand-edit generated output:

```bash
uv run --locked pyganini generate
uv run --locked pyganini check
uv run --locked pyganini routes list
```

For a refactor, compare paths and helpers before/after and explain representative
URLs with `routes explain`. For a nested or external working directory use
`--app-root <actual-root>`. `check` reports stale files without writing them.
Run it before regeneration when diagnosing stale output. Restart application
imports after generation; a live server can otherwise retain old captures.

If asset fingerprinting is enabled, build final app assets first, then check
their managed projection. Ordinary generate/check includes the enabled assets.
Jinja body edits and external content edits do not need route generation unless
ownership/declarations changed.

## Evidence by phase

- Source inspection establishes route/owner/layout/handler evidence without
  importing or executing app code. Generation does not compile Jinja.
- Import/startup validates generated runtime captures and supported callables.
- Request tests establish actual HTML, layout inclusion/exclusion, headers,
  escaping, 404/405, and mount-prefix behavior. Use Starlette TestClient or the
  app's existing ASGI testing boundary.
- Browser checks establish actual HTMX swaps, script loading, SSE delivery,
  overlay UI, or island lifecycle when server tests cannot establish them.
  Choose checks appropriate to the change; plain server-rendered responses do
  not always need browser automation.

Use the smallest focused regression for a testable bug before fixing it, and
verify failure for the intended reason. Add success and reachable edge-case
coverage for the changed public behavior. Keep validation and CSRF ordering
visible; a passing form render does not prove mutation policy.

## Typing and final checks

Generate before type checking imports of `app._pyganini`. Run the app's Ruff,
mypy, Pyright, and pytest checks if configured. Common commands are:

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy app
uv run --locked pyright app
uv run --locked pytest
```

Do not install all these tools or weaken their settings just because this skill
mentions them. Honor the project's dependency/quality policy. Check typed kit
creator/handler relationships and generated helper consumers when applicable.
Keep Jinja async mode disabled and app I/O outside templates.

Review generated diffs against source ownership, update affected app docs, and
stop task-owned servers. Report which commands ran, what evidence they prove,
and any unrun or unavailable checks. A localhost request does not qualify
production deployment, proxy buffering, load, security policy, or publication.
