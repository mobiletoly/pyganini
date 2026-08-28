"""Application-owned Starlette host for the contact directory."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path

from pyganini import TemplateInspectionMode, browser, csrf, sse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app._pyganini.asgi import create_router
from assets import pyganini_assets_gen as assets

from .contacts import ContactRepository
from .dependencies import Dependencies
from .errors import route_error_handler
from .security import ExamplePolicyMiddleware, ImmutableAssetCacheMiddleware

ASSET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "dist"
FINGERPRINTED_ASSET_PATHS = tuple(
    asset.path.removeprefix("/assets/") for asset in assets.manifest().values()
)


async def events(request: Request) -> StreamingResponse:
    """Return one finite application-owned SSE proof stream."""
    last_id = sse.last_event_id(request) or "start"

    async def body() -> AsyncIterator[bytes]:
        yield sse.encode_comment("connected")
        yield sse.encode_event(
            sse.Event(
                id="42",
                name="audit",
                data='<span data-sse-event="ignored">Ignored SSE event</span>',
            )
        )
        yield sse.encode_event(
            sse.Event(
                id="43",
                name="contact",
                retry=2_000,
                data=(
                    '<span data-sse-event="contact">Named SSE contact; '
                    f"last-event-id: {last_id}</span>"
                ),
            )
        )

    return StreamingResponse(
        body(),
        media_type=sse.MEDIA_TYPE,
        headers={"Cache-Control": "no-cache"},
    )


def create_app(
    *,
    dependencies: Dependencies | None = None,
    template_inspection: TemplateInspectionMode = TemplateInspectionMode.OFF,
) -> Starlette:
    """Construct a fresh host application and dependency state."""
    selected_dependencies = dependencies or Dependencies(
        repository=ContactRepository(),
        csrf=csrf.Guard(secret=secrets.token_bytes(32)),
    )
    application = Starlette(
        routes=[
            Mount(
                "/assets",
                app=ImmutableAssetCacheMiddleware(
                    StaticFiles(directory=ASSET_DIRECTORY),
                    fingerprinted_paths=FINGERPRINTED_ASSET_PATHS,
                ),
                name="assets",
            ),
            Mount("/pyganini", app=browser.create_app(), name="pyganini-browser"),
            Route("/events", endpoint=events, methods=["GET"]),
            Mount(
                "/",
                app=create_router(
                    error_handler=route_error_handler,
                    template_inspection=template_inspection,
                ),
            ),
        ]
    )
    application.state.dependencies = selected_dependencies
    application.state.template_inspection = template_inspection
    application.add_middleware(csrf.TokenMiddleware, guard=selected_dependencies.csrf)
    application.add_middleware(ExamplePolicyMiddleware)
    return application


def create_development_app() -> Starlette:
    """Construct the application with explicitly selected development inspection."""
    value = os.environ.get("PYGANINI_TEMPLATE_INSPECTION", "overlay")
    try:
        mode = TemplateInspectionMode(value)
    except ValueError as error:
        raise RuntimeError(
            "PYGANINI_TEMPLATE_INSPECTION must be off, comments, or overlay"
        ) from error
    return create_app(template_inspection=mode)


app: Starlette = create_app()
