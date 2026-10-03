# Application-owned development

Pyganini generates and checks routes. Applications own their ASGI server,
watcher, browser refresh policy, and asset compilation. The full-feature and
content examples share one small repository supervisor in
`examples/dev_support.py`; it is not an installed Pyganini API or CLI command.

From either example directory:

```text
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 python dev.py --port 8000 --reload-path content
```

Each wrapper supplies its explicit directory and Uvicorn development factory.
Defaults are loopback `127.0.0.1` and port `8000`; `--host` and `--port` select
other values. The loop supports macOS and Linux. Native Windows process-tree
supervision remains unsupported.

## Save behavior

| Changed input | Work before notification | Server |
| --- | --- | --- |
| Python below `app/` | Generate, check, replace, then publish a revision | Replaced |
| Final files below `assets/build` | Generate assets/routes, check, replace, then publish | Replaced |
| Existing `.jinja` templates | Publish a revision | Same PID |
| External content or another reload path | Publish a revision | Same PID |
| A mixed batch | Complete preparation and replacement, then publish once | Replaced |

A content/template batch runs no generator or asset command and changes neither
bytes nor mtimes of generated route products. Content reads remain live.
Invalid metadata or bodies show the application-owned error page, including
500 when appropriate; repairing the save refreshes the valid page. The watcher
does not parse content, suppress errors, or serve a cached last-good result.
A new nested content page needs metadata and one body, without a route handler.
Changes to route Python, layout ownership, or template names require generation.

Failed preparation retains the working server and publishes no revision. A
child that exits is reaped and reported once; the loop waits for a subsequent
Python or final asset edit. It does not enter a timed restart loop. Asset source
compilation, such as Vite, remains a separate application command.

## External watch paths

Both examples include `content` by default. Repeat `--reload-path PATH` to add
an ordinary file or directory, relative to the example root or absolute.
Identical paths are deduplicated. Paths must exist initially and must be disjoint
from each other, `app/`, generated routes, and asset build/dist trees. Links,
reparse points, and special files are rejected. Configuration errors stop before
preparation or server startup.

Directory roots are recursive. A deleted directory root terminates the loop.
An exact-file root is watched through its parent, but sibling edits are ignored;
that file may be deleted and recreated. Generated output, coordination files,
`__pycache__`, `.pyc`, `.pyo`, names starting with `.#`, and names ending with `~`
do not produce refresh loops. Editor save operations for regular content remain
visible.

## Explicit browser channel

The supervisor creates a temporary revision file containing a session UUID and
an increasing integer. It atomically replaces this file after an accepted batch
and passes its absolute path to the child as `PYGANINI_EXAMPLE_RELOAD_FILE`.
A failed publication is terminal and performs process cleanup.

Only the explicit development factory mounts `/_example/reload`, before the
root generated router. It reads the file in a worker, polls every 250 ms, emits
an initial named `reload` SSE event and then changed revisions, and sends comment
heartbeats every 15 seconds. Responses use `Cache-Control: no-cache`. Disconnects
cancel the stream; missing or unreadable state logs an application error and
ends it. There is no global subscriber registry.

The development root layout visibly includes fingerprinted `dev-reload.js`
with a `data-events-url` bound through trusted ASGI `root_path`. Native
EventSource remembers the first revision without refreshing. A later different
revision triggers a full page reload. Reconnects compare against the remembered
revision, so disconnected edits and child replacement remain observable. A new
page establishes its own baseline; a new supervisor UUID prevents revision
reuse. Page exit closes the stream. Mounted hosts retain their public prefix.

Production factories expose neither the endpoint nor script even if the
environment variable is present. The host still owns deployment, authentication,
CSP, and network policy. Pyganini adds no proxy, client state, script injection,
framework watcher, or development server command.

## Shutdown and packaged content

Ctrl-C and SIGTERM stop the child process group and reap descendants. Cleanup
uses bounded SIGINT, SIGTERM, and SIGKILL escalation and removes the task-owned
temporary directory. Cleanup failure terminates with an error.

This loop is for ordinary external files. Packaged immutable resources still
require normal build/restart, and their `importlib.resources.as_file` extraction
context must outlive the application. Watching a temporary extraction does not
make the packaged resource mutable.
