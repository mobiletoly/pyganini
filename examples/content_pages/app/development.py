"""Explicit development-only revision stream; production does not install it."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

from pyganini import sse
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

_LOG = logging.getLogger(__name__)


async def revisions(request: Request, path: Path | None) -> AsyncIterator[bytes]:
    previous: str | None = None
    heartbeat = time.monotonic()
    while not await request.is_disconnected():
        try:
            if path is None:
                raise OSError("Development revision file is not configured")
            revision = await run_in_threadpool(path.read_text, encoding="ascii")
        except (OSError, UnicodeError):
            _LOG.exception("Development reload stream stopped: revision read failed")
            return
        if revision != previous:
            yield sse.encode_event(sse.Event(name="reload", data=revision))
            previous = revision
            heartbeat = time.monotonic()
        elif time.monotonic() - heartbeat >= 15:
            yield sse.encode_comment("reload heartbeat")
            heartbeat = time.monotonic()
        await asyncio.sleep(0.25)


def install(application: Starlette) -> Starlette:
    value = os.environ.get("PYGANINI_EXAMPLE_RELOAD_FILE")
    path = Path(value) if value else None

    async def events(request: Request) -> StreamingResponse:
        return StreamingResponse(
            revisions(request, path),
            media_type=sse.MEDIA_TYPE,
            headers={"Cache-Control": "no-cache"},
        )

    application.routes.insert(0, Route("/_example/reload", events, methods=["GET"]))
    application.state.dev_reload_enabled = path is not None
    return application
