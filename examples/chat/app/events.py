"""Application-owned Server-Sent Event endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

from pyganini import sse
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.room import ChatRoom, Message

EVENTS_PATH = "/chat/events"
EVENT_NAME = "chat-message"
_MAX_EVENT_ID = (1 << 63) - 1
_MAX_EVENT_ID_TEXT = str(_MAX_EVENT_ID)


def _positive_integer(value: str) -> int | None:
    if (
        not value
        or len(value) > len(_MAX_EVENT_ID_TEXT)
        or not value.isascii()
        or not value.isdecimal()
        or (len(value) == len(_MAX_EVENT_ID_TEXT) and value > _MAX_EVENT_ID_TEXT)
    ):
        return None
    result = int(value)
    return result if result > 0 else None


def event_after_id(request: Request) -> int:
    header_values = request.headers.getlist(sse.HEADER_LAST_EVENT_ID)
    if len(header_values) == 1:
        header_id = _positive_integer(header_values[0])
        if header_id is not None:
            return header_id

    query_values = request.query_params.getlist("after")
    if len(query_values) == 1:
        query_id = _positive_integer(query_values[0])
        if query_id is not None:
            return query_id
    return 0


async def event_frames(
    room: ChatRoom,
    after_id: int,
    render_message: Callable[[Message], str],
    heartbeat_seconds: float,
) -> AsyncGenerator[bytes]:
    subscription = await room.subscribe(after_id)
    try:
        yield sse.encode_comment("connected")
        pending = iter(subscription.replay)
        while True:
            message = next(pending, None)
            if message is None:
                try:
                    message = await asyncio.wait_for(
                        subscription.queue.get(), timeout=heartbeat_seconds
                    )
                except TimeoutError:
                    yield sse.encode_comment("keep-alive")
                    continue
            html = await run_in_threadpool(render_message, message)
            yield sse.encode_event(
                sse.Event(
                    id=str(message.identifier),
                    name=EVENT_NAME,
                    data=html,
                )
            )
    finally:
        await room.unsubscribe(subscription.identifier)


def create_events_endpoint(
    room: ChatRoom,
    render_message: Callable[[Message], str],
    heartbeat_seconds: float,
) -> Callable[[Request], Awaitable[Response]]:
    async def events(request: Request) -> Response:
        if request.method != "GET":
            return Response(status_code=405, headers={"Allow": "GET"})
        return StreamingResponse(
            event_frames(
                room,
                event_after_id(request),
                render_message,
                heartbeat_seconds,
            ),
            media_type=sse.MEDIA_TYPE,
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return events
