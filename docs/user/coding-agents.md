# Coding Agents

Install the [Pyganini App skill](../skills/pyganini-app/SKILL.md) to give a coding
agent application-development guidance: setup, filesystem routes, Jinja layouts,
HTMX fragments/actions, kits and mounts, content pages, assets, and validation.
Install the complete package, including its task-specific references. It works
without a Pyganini or Goldr framework checkout.

The skill is for downstream applications. Pyganini's framework repository has
its own contributor policy; do not copy that policy into your application.

## Codex

Ask Codex to install the GitHub skill directory:

```text
$skill-installer install https://github.com/mobiletoly/pyganini/tree/main/docs/skills/pyganini-app
```

Then invoke it for a concrete application task:

```text
Use $pyganini-app to add a route-local HTMX form to this application.
```

Its description also permits automatic selection for relevant Pyganini app work.
If a newly installed skill does not appear, restart the agent session.

## Claude Code

Add the repository marketplace and install its single-skill plugin:

```bash
claude plugin marketplace add mobiletoly/pyganini --sparse .claude-plugin
claude plugin install pyganini-app@pyganini
```

The marketplace fetches metadata first; the plugin source selects only
`docs/skills/pyganini-app`. Use a current Claude Code release supporting
`git-subdir` sources and root single-skill plugins; the package validation target
is Claude Code 2.1.193. Restart the session after installation, then ask for a
concrete task such as:

```text
Use the Pyganini App skill to review this application's routes and generated URLs.
```

## Application instructions

Merge the following section into your application's existing `AGENTS.md` rather
than replacing project-specific rules. Adjust commands to your project's tools
and scripts. Consumer installation is not restricted to uv; these commands suit
a uv-managed app with the corresponding quality tools installed.

````md
# Pyganini Application Rules

This application uses Pyganini. Use the Pyganini App skill when available.

- Keep the app server-first, HTML-first, and Python-native. Keep HTMX attributes
  visible in Jinja; do not add a second router, SPA, or framework-owned state.
- The app owns the ASGI host/server, middleware, auth, sessions, persistence,
  validation, dependency wiring, static files, cache policy, and deployment.
- Keep an empty `[tool.pyganini]` table in the app's `pyproject.toml`.
- Routes are regular packages below `app/routes`, with `__init__.py`. `route.py`
  declares page, fragment, and action endpoints through one direct `Route` value.
- Use lowercase Python directory names and `by_<param>` dynamic packages.
  Keep handlers and `.jinja` templates local to their route.
- `layout.py` marks adjacent `layout.jinja`. `middleware.py` declares one direct
  non-empty tuple of application-owned Starlette middleware.
- Use shared kits or non-live `app/mounts` source trees only for real reuse;
  live owners retain URL selection, request state, layout ancestry, and policy.
- Pass generated URL values explicitly into templates. Bind helpers with
  `urls.with_base_path(request.scope.get("root_path", ""))` for mounted hosts.
- Finish I/O before synchronous Jinja rendering. Use async handlers for live
  Starlette body/form/upload APIs; sync handlers run in workers.
- Never hand-edit or add application code under `app/_pyganini`. Regenerate.
  Do not hand-edit managed asset output or its generated lookup/state.
- Do not assume optional content, assets, CSRF, SSE, or inspection is configured.
  Preserve the app's existing policy and feature choices.

After declaration changes, generate, check, and inspect:

```bash
uv run --locked pyganini generate
uv run --locked pyganini check
uv run --locked pyganini routes list
```

Run the existing focused tests and configured quality checks. Use these when
they are the project's chosen commands:

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy app
uv run --locked pyright app
uv run --locked pytest
```

Use `--app-root` when invoking Pyganini from outside the app. Restart the host
after route generation. Check actual HTMX/browser behavior when server tests
cannot establish it, and stop development servers started for the task.
````

## Package maintenance

The skill package and this guide are maintained with Pyganini's public contracts.
Changes to route grammar, public APIs, generated interfaces, or supported tooling
must update the affected references and their executable examples. Plugin
versioning is independent of the framework package version. Local package and
ASGI checks do not establish successful hosted installation; publishing the
repository changes and verifying remote installation are separate steps.
