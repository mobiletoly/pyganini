"""Application shell values shared by rendered pages."""

from __future__ import annotations

from starlette.requests import Request

from app._pyganini.urls import urls
from assets import pyganini_assets_gen as assets


def root_path(request: Request) -> str:
    """Return the host-supplied ASGI root path."""
    value = request.scope.get("root_path", "")
    return value if isinstance(value, str) else ""


def layout(request: Request) -> dict[str, object]:
    """Build the explicit root layout mapping."""
    base_path = root_path(request)
    return {
        "urls": urls.with_base_path(base_path),
        "stylesheet_url": assets.path("app.css", base_path=base_path),
        "htmx_script_url": assets.path(
            "vendor/htmx.min.js",
            base_path=base_path,
        ),
    }
