"""Server-rendered About page handler."""

from __future__ import annotations

from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls
from app.routes.handlers import build_layout, root_path


def page(request: Request) -> Page:
    """Render the entirely server-owned navigation destination."""
    app_urls = urls.with_base_path(root_path(request))
    return Page(
        context={"root_url": app_urls.root.path},
        metadata=PageMetadata(
            title="About the React island - Pyganini",
            description="The server-rendered boundary around the React island.",
        ),
        layout=build_layout(request),
    )
