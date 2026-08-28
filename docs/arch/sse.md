# Server-Sent Event Wire Architecture

src/pyganini/sse.py owns one narrow boundary:

~~~text
application route and event data
-> pyganini.sse Event and wire encoders
-> bytes iterator
-> Starlette StreamingResponse
-> ASGI server
~~~

The module depends on the standard library and Starlette's public
starlette.requests.Request type. It does not import route declarations,
dispatch, generation, inspection, rendering, CSRF, or HTMX code.

## Public contract

The module exports exactly MEDIA_TYPE, HEADER_LAST_EVENT_ID, Event,
encode_event, encode_comment, and last_event_id. The Pyganini package root
exports only the module as sse; it does not re-export the event type,
constants, or functions.

Event is a frozen, slotted, keyword-only dataclass with data: str,
id: str | None, name: str | None, and retry: int | None. Construction
validates runtime types and values before a caller can yield a partial frame:

- data must be a string;
- ID must be a string or None and rejects NULL, CR, and LF;
- name must be a string or None and rejects CR and LF; and
- retry must be an integer other than bool, or None, and must be non-negative.

Wrong types raise TypeError; invalid values raise ValueError. Messages identify
only the field and rule, not the supplied payload.

## Wire algorithm

Both encoders normalize input with two ordered replacements: CRLF becomes LF,
then each remaining CR becomes LF. Splitting on LF preserves empty strings at
the beginning, between lines, and at the end.

encode_event builds a complete text frame in this order:

1. id: <value> followed by LF when ID is not None;
2. event: <value> followed by LF when name is not None;
3. retry: <milliseconds> followed by LF when retry is not None;
4. one data: <line> field followed by LF for every logical data line; and
5. one final LF.

The default empty data value therefore emits data: followed by a space and two
LF characters. Explicit empty ID and name values remain present, and retry zero
remains present. The complete text is encoded once as UTF-8, so an unpaired
surrogate raises UnicodeEncodeError without replacement or a partial return.

encode_comment emits a colon, one space, each logical comment line, and LF,
then one final LF. An empty comment emits a colon, one space, and two LF
characters. Both functions return deterministic bytes and never perform I/O.

last_event_id validates that its argument is a Starlette Request, then returns
request.headers.get("Last-Event-ID", ""). Header lookup, casing, and request
state remain Starlette and application concerns.

## Response and failure ownership

Pyganini does not add a response subclass, response factory, stream object, writer,
flusher, ASGI send wrapper, or automatic header map. Starlette owns
StreamingResponse, iterator consumption, ASGI messages, response encoding,
cancellation, and the started-response boundary. Application exceptions and
cancellation retain their identity.

The application owns route registration, authorization, subscriber state,
queues, persistence, replay, event IDs, payload serialization, cache headers,
proxy buffering, compression, timeouts, disconnect checks, backpressure, and
resource cleanup. It must use try and finally in its iterator when a
long-lived resource needs cleanup.

Jinja rendering, if used, finishes before an Event is constructed. The helper
does not render, escape, sanitize, parse JSON, or impose a size limit. It does
not schedule comments, select retry values, or interpret event IDs.

The full-feature proof uses a finite application-owned Starlette Route at
/events. It proves public framing and host composition without adding a
generated route, browser client, background task, queue, replay system, or
production streaming guarantee.

Named-event browser swapping is a separate `pyganini.browser` boundary. Its
fixed JavaScript hook converts only the selected named message to HTMX's
unnamed swap path. It does not alter wire encoding, response construction,
subscriber ownership, or stream lifecycle.
