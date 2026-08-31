"""Handler for the selectively exposed audit page."""

from pyganini import Page, PageMetadata
from starlette.requests import Request

from app.mounts.reports.handlers import ReportKit
from app.shell import layout


def page(report: ReportKit, request: Request) -> Page:
    """Render the audit tools for an owner that selected this child."""
    return Page(
        context={"report": report},
        metadata=PageMetadata(
            title="Admin Report Tools - Pyganini Kit Routes",
            description="Admin-only tools from the reusable reports source.",
        ),
        layout=layout(request),
    )
