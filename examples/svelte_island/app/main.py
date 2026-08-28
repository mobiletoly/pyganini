"""Application-owned Starlette host for the bounded Svelte island."""

from __future__ import annotations

import secrets
from pathlib import Path

from pyganini import csrf
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app._pyganini.asgi import create_router
from assets import pyganini_assets_gen as assets

from .security import ImmutableAssetCacheMiddleware
from .state import Dependencies, ProjectStore

ASSET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "dist"
FINGERPRINTED_ASSET_PATHS = tuple(
    asset.path.removeprefix("/assets/") for asset in assets.manifest().values()
)


def create_app(*, dependencies: Dependencies | None = None) -> Starlette:
    """Construct a fresh host and fresh application state by default."""
    selected = dependencies or Dependencies(
        store=ProjectStore(),
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
            Mount("/", app=create_router()),
        ]
    )
    application.state.dependencies = selected
    application.add_middleware(csrf.TokenMiddleware, guard=selected.csrf)
    return application


app: Starlette = create_app()
