"""Application-owned content bootstrap and Starlette host."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from pyganini import AdditionalPage, Page, PageMetadata, TemplateInspectionMode, content
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app._pyganini.asgi import create_router
from app.shell import layout

ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = ROOT / "content"
_LOG = logging.getLogger(__name__)


def error_handler(request: Request, error: Exception) -> Page:
    status = error.status_code if isinstance(error, HTTPException) else 500
    if status == 500:
        _LOG.error("Page source failed", exc_info=error)
    return Page(
        metadata=PageMetadata("Page not available"),
        layout=layout(request),
        status_code=status,
    )


def create_app(
    *,
    content_root: Path = CONTENT_ROOT,
    template_inspection: TemplateInspectionMode = TemplateInspectionMode.OFF,
) -> Starlette:
    pages = content.new(content.Config(root=content_root))

    def source(request: Request) -> AdditionalPage | None:
        page = pages.resolve(request)
        return None if page is None else replace(page, layout=layout(request))

    return Starlette(
        routes=[
            Mount("/assets", app=StaticFiles(directory=ROOT / "assets/dist")),
            Mount(
                "/",
                app=create_router(
                    additional_page_source=source,
                    error_handler=error_handler,
                    template_inspection=template_inspection,
                ),
            ),
        ]
    )


def create_development_app() -> Starlette:
    from app.development import install

    return install(create_app())


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate application-owned content")
    parser.add_argument("--check-content", action="store_true", required=True)
    parser.parse_args()
    content.check(CONTENT_ROOT)
    print("Content checked.")


if __name__ == "__main__":
    main()
