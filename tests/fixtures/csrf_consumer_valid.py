from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from pyganini import csrf

SECRET: bytes = b"0123456789abcdef0123456789abcdef"
guard = csrf.Guard(secret=SECRET, max_age=300, same_site="lax")


async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
    return None


middleware: ASGIApp = csrf.TokenMiddleware(downstream, guard=guard)


def consume(request: Request) -> tuple[str, str]:
    value = csrf.token(request)
    guard.validate(request, value)
    return value, csrf.headers(value)
