"""Application-owned SSE endpoint behavior."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence

import pytest
from pyganini import create_environment
from starlette.requests import Request

from app.events import EVENT_NAME, create_events_endpoint, event_after_id, event_frames
from app.room import ChatRoom, Message


def _request(
    *,
    method: str = "GET",
    query: bytes = b"",
    headers: Sequence[tuple[bytes, bytes]] = (),
) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/chat/events",
            "raw_path": b"/chat/events",
            "query_string": query,
            "headers": headers,
            "client": ("test", 50000),
            "server": ("test", 80),
            "root_path": "",
        }
    )


@pytest.mark.parametrize(
    ("http_request", "expected"),
    [
        (_request(query=b"after=7"), 7),
        (_request(query=b"after=7", headers=[(b"last-event-id", b"9")]), 9),
        (_request(query=b"after=7", headers=[(b"last-event-id", b"bad")]), 7),
        (_request(query=b"after=7&after=8"), 0),
        (
            _request(
                query=b"after=7",
                headers=[(b"last-event-id", b"9"), (b"last-event-id", b"10")],
            ),
            7,
        ),
        (_request(query=b"after=0"), 0),
        (_request(query=b"after=-1"), 0),
        (_request(query=b"after=9223372036854775807"), 9223372036854775807),
        (_request(query=b"after=9223372036854775808"), 0),
        (_request(query=b"after=" + (b"9" * 4_301)), 0),
    ],
)
def test_event_cursor_precedence_and_validation(
    http_request: Request, expected: int
) -> None:
    assert event_after_id(http_request) == expected


@pytest.mark.anyio
async def test_events_endpoint_rejects_head_before_streaming() -> None:
    endpoint = create_events_endpoint(ChatRoom(), str, heartbeat_seconds=1)

    response = await endpoint(_request(method="HEAD"))

    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


def _render_message() -> Callable[[Message], str]:
    environment = create_environment()
    template = environment.get_template("routes/chat/message.jinja")

    def render(message: Message) -> str:
        return template.render(message=message)

    return render


@pytest.mark.anyio
async def test_event_frames_emit_comment_replay_and_escaped_named_html() -> None:
    room = ChatRoom()
    message = await room.publish("<Ada>", "{{ value }} <script>alert(1)</script>")
    frames = event_frames(room, 0, _render_message(), heartbeat_seconds=1)
    assert await anext(frames) == b": connected\n\n"
    event = await anext(frames)
    await frames.aclose()

    assert f"id: {message.identifier}\n".encode() in event
    assert f"event: {EVENT_NAME}\n".encode() in event
    assert b"&lt;Ada&gt;" in event
    assert b"{{ value }} &lt;script&gt;alert(1)&lt;/script&gt;" in event
    assert b"<script>" not in event


@pytest.mark.anyio
async def test_event_frames_deliver_live_messages_and_heartbeats() -> None:
    room = ChatRoom()

    def render(message: Message) -> str:
        return str(message)

    frames = event_frames(room, 0, render, heartbeat_seconds=0.001)
    assert await anext(frames) == b": connected\n\n"
    assert await anext(frames) == b": keep-alive\n\n"

    published = await room.publish("Ada", "Live")
    event = await anext(frames)
    await frames.aclose()
    assert f"id: {published.identifier}\n".encode() in event


class _RecordingRoom(ChatRoom):
    def __init__(self) -> None:
        super().__init__()
        self.unsubscribed: list[int] = []

    async def unsubscribe(self, subscription_id: int) -> None:
        await super().unsubscribe(subscription_id)
        self.unsubscribed.append(subscription_id)


@pytest.mark.anyio
async def test_closing_event_frames_unsubscribes() -> None:
    room = _RecordingRoom()

    async def consume() -> AsyncGenerator[bytes]:
        frames = event_frames(room, 0, str, heartbeat_seconds=1)
        yield await anext(frames)
        await frames.aclose()

    stream = consume()
    assert await anext(stream) == b": connected\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert room.unsubscribed == [1]


@pytest.mark.anyio
async def test_cancelling_event_frames_unsubscribes() -> None:
    room = _RecordingRoom()
    frames = event_frames(room, 0, str, heartbeat_seconds=60)
    assert await anext(frames) == b": connected\n\n"

    pending_frame = asyncio.create_task(anext(frames))
    await asyncio.sleep(0)
    assert not pending_frame.done()

    pending_frame.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_frame
    assert room.unsubscribed == [1]
