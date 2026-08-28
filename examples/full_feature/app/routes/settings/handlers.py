"""Handlers for the settings page."""

from __future__ import annotations

from pyganini import Page, PageMetadata, nav
from starlette.requests import Request

from app._pyganini.urls import urls

from ..handlers import build_layout


def page(request: Request) -> Page:
    """Render the static settings page."""
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    navigation = nav(request).navigation()
    return Page(
        context={"urls": app_urls, "navigation": navigation},
        metadata=PageMetadata(
            title="Settings - Pyganini Contact Directory",
            description="Application-owned settings for the example.",
        ),
        layout=build_layout(request, "settings"),
    )
