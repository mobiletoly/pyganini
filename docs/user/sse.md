# Server-Sent Event Helpers

Pyganini includes an optional pyganini.sse module for deterministic Server-Sent
Event wire framing. It does not create a route, response class, stream manager,
subscriber registry, replay store, browser client, or deployment policy.

Import the module:

~~~python
from pyganini import sse
~~~

The public module names are sse.Event, sse.encode_event,
sse.encode_comment, sse.last_event_id, sse.MEDIA_TYPE, and
sse.HEADER_LAST_EVENT_ID.

## Events

Event is a frozen, slotted, keyword-only value. Its optional id, name, and
retry fields use None to omit a field. An explicit empty ID emits an empty id
field, which lets a browser reset its last event ID. Retry is a non-negative
integer number of milliseconds, and zero is valid.

~~~python
event = sse.Event(
    id="42",
    name="contact",
    retry=2_000,
    data="<li>Ada Lovelace</li>",
)
frame = sse.encode_event(event)
~~~

The event encoder writes fields in ID, event name, retry, and data order.
Every data line is emitted as a separate data field. CRLF and CR are
normalized to LF, including leading, interior, and trailing empty logical
lines. The event ends with one blank line. The returned value is UTF-8 bytes.

Event IDs reject NULL, CR, and LF. Event names reject CR and LF. The helper
does not trim, normalize Unicode, escape HTML, parse JSON, or impose a payload
size limit. Unpaired surrogates raise Python's normal UnicodeEncodeError.

Comments use the same line normalization and return a complete frame:

~~~python
heartbeat = sse.encode_comment("connected")
# b": connected\n\n"
~~~

Comments are only wire frames. Pyganini does not assign heartbeat meaning or
schedule them.

## Starlette streaming

The application owns the GET route, authorization, iterator, cleanup,
disconnect checks, replay, cache policy, and response construction. Use
Starlette's public StreamingResponse directly:

~~~python
from collections.abc import AsyncIterator

from pyganini import sse
from starlette.requests import Request
from starlette.responses import StreamingResponse


async def events(request: Request) -> StreamingResponse:
    last_id = sse.last_event_id(request)

    async def body() -> AsyncIterator[bytes]:
        yield sse.encode_comment("connected")
        yield sse.encode_event(
            sse.Event(
                id="43",
                name="contact",
                retry=2_000,
                data=f"last-event-id: {last_id or 'start'}",
            )
        )

    return StreamingResponse(
        body(),
        media_type=sse.MEDIA_TYPE,
        headers={"Cache-Control": "no-cache"},
    )
~~~

Starlette consumes the normal sync or async iterator and owns ASGI messages,
cancellation, and response headers. The application must choose any proxy
buffering, compression, timeout, CORS, CSP, and server policy. A finite
TestClient response proves framing and composition only; it does not prove
production flushing, proxy behavior, scaling, reconnect replay, or cleanup of
long-lived resources.

## Reconnection headers and rendering

sse.last_event_id(request) reads Starlette's case-insensitive Last-Event-ID
request header and returns its visible text unchanged. A missing or empty
header returns the empty string. The helper does not validate IDs, read query
parameters, or decide whether replay is allowed.

Render Jinja or serialize application data before constructing Event. The SSE
helper receives completed application strings and does not perform template
lookup, rendering, escaping, sanitization, or JSON encoding. HTML payloads
therefore remain an application-owned content and trust decision.

## Named browser events

HTMX 4 dispatches named SSE messages as DOM events instead of swapping their
HTML. The optional `pyganini.browser` helper lets one visible
`pyganini-sse-event` attribute select a named event for the normal unnamed swap
path. Mount the helper app explicitly and load the application-owned local
HTMX core and SSE extension before the helper. When these scripts are in the
document head, load the three scripts sequentially without `async` or `defer`
so every extension is registered before HTMX processes the document:

~~~python
from pyganini import browser
from starlette.routing import Mount

Mount("/pyganini", app=browser.create_app(), name="pyganini-browser")
~~~

~~~html
<script src="/assets/vendor/htmx.min.js"></script>
<script src="/assets/vendor/hx-sse.min.js"></script>
<script src="/pyganini/pyganini-sse-event.js"></script>
<div
  hx-sse:connect="/events"
  pyganini-sse-event="contact"
  hx-config='{"sse":{"reconnect":false,"pauseOnBackground":false}}'
  hx-swap="beforeend">
</div>
~~~

The application owns both URLs, mounting, CSP, authorization, caching, and
deployment. The stable helper response uses `Cache-Control: no-cache` and a
strong content ETag. This browser behavior does not change `pyganini.sse` framing
or move stream production into Pyganini.

## Runnable chat example

The [Chat example](../../examples/chat) connects generated pages and bounded
form actions to an application-owned `/chat/events` stream. Its room handles
replay, heartbeat timing, subscriber registration, and disconnect cleanup. The
stream renders one shared Jinja message partial before `sse.encode_event()` and
loads the local HTMX scripts before Pyganini's named-event browser helper.

Run it from `examples/chat`:

~~~bash
uv sync --locked --all-groups --python 3.14
uv run --locked --python 3.14 uvicorn app.main:app --reload
~~~

Open two browser contexts to test live delivery. The example README documents
its unsigned cookie, process-local state, unbounded queues, and proxy limits.
