"""Handlers for the example root route."""

from __future__ import annotations

from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls
from app.shell import layout, root_path


def page(request: Request) -> Page:
    """Render links to both live reports owners."""
    return Page(
        context={"urls": urls.with_base_path(root_path(request))},
        metadata=PageMetadata(
            title="Pyganini Kit Routes",
            description="One reusable reports source mounted below two live owners.",
        ),
        layout=layout(request),
    )
