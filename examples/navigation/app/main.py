"""Application-owned Starlette host for the Navigation example."""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app._pyganini.asgi import create_router

ASSET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "dist"


def create_app() -> Starlette:
    return Starlette(
        routes=[
            Mount(
                "/assets",
                app=StaticFiles(directory=ASSET_DIRECTORY),
                name="assets",
            ),
            Mount("/", app=create_router()),
        ]
    )


app: Starlette = create_app()
