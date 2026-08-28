"""Small typed helpers for Server-Sent Event wire framing."""

# pyright: reportUnnecessaryIsInstance=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from starlette.requests import Request

MEDIA_TYPE: Final = "text/event-stream"
HEADER_LAST_EVENT_ID: Final = "Last-Event-ID"

__all__ = [
    "HEADER_LAST_EVENT_ID",
    "MEDIA_TYPE",
    "Event",
    "encode_comment",
    "encode_event",
    "last_event_id",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """One validated Server-Sent Event value."""

    data: str = ""
    id: str | None = None
    name: str | None = None
    retry: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.data, str):
            raise TypeError("data must be a str")
        if self.id is not None:
            if not isinstance(self.id, str):
                raise TypeError("id must be a str or None")
            if any(character in self.id for character in "\x00\r\n"):
                raise ValueError("id must not contain NULL, CR, or LF")
        if self.name is not None:
            if not isinstance(self.name, str):
                raise TypeError("name must be a str or None")
            if any(character in self.name for character in "\r\n"):
                raise ValueError("name must not contain CR or LF")
        if self.retry is not None:
            if isinstance(self.retry, bool) or not isinstance(self.retry, int):
                raise TypeError("retry must be an int or None")
            if self.retry < 0:
                raise ValueError("retry must be zero or greater")


def _split_lines(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n")


def encode_event(event: Event) -> bytes:
    """Encode one event as a complete UTF-8 SSE frame."""
    if not isinstance(event, Event):
        raise TypeError("event must be an sse.Event")

    lines: list[str] = []
    if event.id is not None:
        lines.append(f"id: {event.id}\n")
    if event.name is not None:
        lines.append(f"event: {event.name}\n")
    if event.retry is not None:
        lines.append(f"retry: {event.retry}\n")
    lines.extend(f"data: {line}\n" for line in _split_lines(event.data))
    lines.append("\n")
    return "".join(lines).encode("utf-8")


def encode_comment(comment: str) -> bytes:
    """Encode one complete UTF-8 SSE comment frame."""
    if not isinstance(comment, str):
        raise TypeError("comment must be a str")

    lines = [f": {line}\n" for line in _split_lines(comment)]
    lines.append("\n")
    return "".join(lines).encode("utf-8")


def last_event_id(request: Request) -> str:
    """Return the browser's Last-Event-ID request header, if present."""
    if not isinstance(request, Request):
        raise TypeError("request must be a starlette.requests.Request")
    return request.headers.get(HEADER_LAST_EVENT_ID, "")
