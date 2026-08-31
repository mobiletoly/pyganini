# Chat Example

This example connects generated Pyganini pages and form actions to an
application-owned Server-Sent Event stream. Two browser windows can join one
process-local room and receive named HTML events.

Pyganini owns route dispatch, bounded form capture, Jinja rendering, generated
URLs, SSE framing, and the browser helper. The Starlette application owns the
room, subscribers, replay, heartbeat timing, cookies, and `/chat/events`.

## Run

From `examples/chat`:

```bash
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> in two browser contexts. Use a different display
name in each context, then send a message. The default three-second action delay
keeps the HTMX progress indicator visible before both contexts receive the
`chat-message` event.

The application exposes:

```text
GET,HEAD  /
POST      /join
GET,HEAD  /chat
POST      /chat/message
POST      /chat/sign-out
GET       /chat/events
GET,HEAD  /pyganini/pyganini-sse-event.js
GET,HEAD  /assets/<fingerprinted-path>
```

Pyganini generates the page and action routes. `app/main.py` registers the SSE,
browser-helper, and asset routes before mounting the generated router.

The example vendors `htmx.org` `4.0.0-beta6` core and `hx-sse` from their
[versioned distribution](https://cdn.jsdelivr.net/npm/htmx.org@4.0.0-beta6/dist/)
and serves the fingerprinted files locally.

## Inspect and regenerate

Inspect the route graph and one action:

```bash
uv run --locked --python 3.14 pyganini routes list
uv run --locked --python 3.14 pyganini routes explain /chat/message --method POST
```

Check generated route and asset state without writing:

```bash
uv run --locked --python 3.14 pyganini check
uv run --locked --python 3.14 pyganini assets check
```

Regenerate Pyganini-owned files after changing routes or asset inputs:

```bash
uv run --locked --python 3.14 pyganini generate
uv run --locked --python 3.14 pyganini assets dist
```

## Validate

Run the example checks on Python 3.14, then replace `3.14` with `3.13`:

```bash
uv run --locked --python 3.14 ruff format --check .
uv run --locked --python 3.14 ruff check .
uv run --locked --python 3.14 mypy app tests
uv run --locked --python 3.14 pyright app tests
uv run --locked --python 3.14 pytest -q
```

## Boundaries

The `pyganini_chat_name` cookie stores an unsigned display label. It does not
provide identity, authentication, or authorization.

One process owns all messages and subscriptions. The room retains messages for
the process lifetime and gives each subscriber an unbounded queue. A slow or
disconnected consumer can increase memory use until stream cleanup removes its
subscription. Multiple workers do not share messages, replay state, or queues.

Production deployments need application-selected persistence, authentication,
authorization, queue bounds, abuse controls, and cross-process delivery. Proxy
buffering, compression, idle timeouts, connection limits, and graceful shutdown
also affect long-lived SSE behavior. This example supplies no deployment
configuration or production scaling policy.
