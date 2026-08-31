"""Application-owned display-name cookie helpers."""

from __future__ import annotations

from urllib.parse import quote, unquote

from starlette.requests import Request
from starlette.responses import Response

COOKIE_NAME = "pyganini_chat_name"
MAX_NAME_LENGTH = 80


def usable_name(request: Request) -> str:
    value = request.cookies.get(COOKIE_NAME, "")
    try:
        name = unquote(value, errors="strict").strip()
    except UnicodeError:
        return ""
    return name if 0 < len(name) <= MAX_NAME_LENGTH else ""


def set_name(response: Response, name: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        quote(name, safe=""),
        path="/",
        httponly=True,
        samesite="lax",
    )


def clear_name(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
