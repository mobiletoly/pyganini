# Assets, Development, and SSE

Read only the applicable section for optional asset fingerprinting, app-owned
reload, streaming, or named-event browser helpers.

## Fingerprinted final assets

The app compiles/bundles into `assets/build` and owns `assets/__init__.py`.
Pyganini fingerprints those final regular files into `assets/dist`, writes
`assets/pyganini_assets_gen.py`, and tracks cleanup in
`assets/.pyganini/assets.json`. Do not edit managed products or watch them as
source inputs. Pyganini does not compile CSS/JS, minify, upload, or serve assets.

```bash
uv run --locked pyganini assets dist
uv run --locked pyganini assets check
uv run --locked pyganini assets list --json
```

Normal generate/check includes asset projection when `assets/build` exists.
`assets clean` removes stale state-owned output, not current source input.

```python
from assets import pyganini_assets_gen as assets

css_url = assets.path("app.css", base_path=request.scope.get("root_path", ""))
```

Pass URLs explicitly into templates and mount static delivery in the host
before the catch-all generated router. The app owns cache policy; immutable
caching belongs only on known fingerprinted assets, not blanket application
responses or optional fixed helper resources.

## Development ownership

Use existing project wrappers. Pyganini has no `dev` command, proxy, watcher, or
automatic browser reload. An application-owned supervisor can generate/check
before replacing its server for Python or asset changes, retain a working server
when preparation fails, and ignore managed output to avoid loops. Existing
Jinja body and external content edits need no route regeneration; declaration,
layout ownership, or template-name changes do.

The framework repository's example supervisor is not an installed API. Do not
assume `dev.py` or a sibling checkout exists in a downstream app. Ordinary
app-owned Uvicorn and a project's chosen watch tools are sufficient. Stop any
server started for the task. Bounded React/Svelte islands keep their own builds,
state, lifecycle bridge, and cleanup; Pyganini provides no hydration runtime.

## SSE wire framing

Use Starlette `StreamingResponse` and an app-owned iterator. Pyganini provides
wire helpers, not subscriber, replay, heartbeat scheduling, or stream management:

```python
from collections.abc import AsyncIterator

from pyganini import sse
from starlette.requests import Request
from starlette.responses import StreamingResponse


async def events(request: Request) -> StreamingResponse:
    async def frames() -> AsyncIterator[bytes]:
        yield sse.encode_comment("connected")
        yield sse.encode_event(sse.Event(name="update", data="<p>Ready</p>"))

    return StreamingResponse(
        frames(), media_type=sse.MEDIA_TYPE, headers={"Cache-Control": "no-cache"}
    )
```

Declare this ordinary handler as an explicit GET route. Render HTML or serialize
data before building events. `sse.Event` supports `id`, `name`, `retry`, and
`data`; `encode_event`/`encode_comment` return UTF-8 bytes. `last_event_id(request)`
reads the header without deciding replay policy. The app owns authorization,
disconnect cleanup, buffering, reconnect, and all proxy/server limits. A finite
ASGI response proves framing, not production flushing or stream scalability.

## Optional browser helpers

Explicitly mount `browser.create_app()` at an app-chosen prefix and construct
public helper URLs with the trusted mount prefix. The app supplies HTMX 4 and
its SSE extension, followed sequentially by `browser.SSE_EVENT_HELPER_PATH`.
The helper handles named events selected visibly:

```html
<div hx-sse:connect="/events" pyganini-sse-event="update"
     hx-swap="innerHTML"></div>
```

Replace the illustrative stream URL with a generated route path when represented
by the app graph. Head scripts must load in registration order without async or
defer. Fixed browser helpers use `no-cache`/ETag revalidation; they are not
application assets or a directory static server. Mounting, scripts, CSP, cache,
and stream production remain application-owned.
