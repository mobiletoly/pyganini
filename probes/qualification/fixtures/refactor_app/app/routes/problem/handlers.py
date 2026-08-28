from __future__ import annotations

from starlette.requests import Request


def page(_: Request) -> None:
    raise RuntimeError("qualification request failure")
