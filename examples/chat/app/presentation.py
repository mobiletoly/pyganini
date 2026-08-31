"""Explicit page layout values for the Chat example."""

from __future__ import annotations

from pyganini import browser
from starlette.requests import Request

from app._pyganini.urls import urls
from assets import pyganini_assets_gen as assets


def root_path(request: Request) -> str:
    value = request.scope.get("root_path", "")
    return value if isinstance(value, str) else ""


def layout(request: Request) -> dict[str, object]:
    base_path = root_path(request)
    app_urls = urls.with_base_path(base_path)
    external_base = app_urls.root.path.removesuffix("/")
    return {
        "stylesheet_url": assets.path("app.css", base_path=base_path),
        "htmx_script_url": assets.path("vendor/htmx.min.js", base_path=base_path),
        "sse_extension_script_url": assets.path(
            "vendor/hx-sse.min.js", base_path=base_path
        ),
        "sse_helper_script_url": (
            f"{external_base}/pyganini{browser.SSE_EVENT_HELPER_PATH}"
        ),
    }
