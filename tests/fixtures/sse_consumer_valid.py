from __future__ import annotations

from starlette.requests import Request

from pyganini import sse

event = sse.Event(
    data="<li>Ada Lovelace</li>",
    id="42",
    name="contact",
    retry=2_000,
)


def consume(request: Request) -> tuple[bytes, bytes, str]:
    return (
        sse.encode_event(event),
        sse.encode_comment("connected"),
        sse.last_event_id(request),
    )
