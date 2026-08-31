"""Typed access to application-owned Chat state."""

from __future__ import annotations

from typing import cast

from starlette.requests import Request

from app.room import ChatRoom


def room(request: Request) -> ChatRoom:
    return cast(ChatRoom, request.app.state.room)


def send_delay(request: Request) -> float:
    return cast(float, request.app.state.send_delay)
