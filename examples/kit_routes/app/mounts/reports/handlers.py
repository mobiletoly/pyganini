"""Typed data and handlers for the reusable reports source."""

from __future__ import annotations

from dataclasses import dataclass

from pyganini import FragmentResponse, FragmentRouteResponse, Page, PageMetadata
from starlette.requests import Request

from app.shell import layout


@dataclass(frozen=True, slots=True)
class PeriodOption:
    """One report period offered by both live owners."""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class ReportRow:
    """One row rendered by the shared table template."""

    metric: str
    value: str
    note: str


@dataclass(frozen=True, slots=True)
class ReportURLs:
    """Owner-bound generated URLs supplied to the reusable source."""

    page_url: str
    table_url: str
    audit_url: str | None


@dataclass(frozen=True, slots=True)
class ReportKit:
    """Request-scoped data supplied by one live reports owner."""

    audience: str
    heading: str
    description: str
    periods: tuple[PeriodOption, ...]
    rows: tuple[ReportRow, ...]
    show_audit: bool
    urls: ReportURLs


def selected_period(report: ReportKit, request: Request) -> str:
    """Select one known period or return the documented default."""
    values = request.query_params.getlist("period")
    known = {period.value for period in report.periods}
    return values[0] if len(values) == 1 and values[0] in known else "30d"


def page(report: ReportKit, request: Request) -> Page:
    """Render the shared reports page for one live owner."""
    return Page(
        context={
            "report": report,
            "selected_period": selected_period(report, request),
        },
        metadata=PageMetadata(
            title=f"{report.heading} - Pyganini Kit Routes",
            description=report.description,
        ),
        layout=layout(request),
    )


def table(report: ReportKit, request: Request) -> FragmentRouteResponse:
    """Render the owner-specific table without either layout."""
    return FragmentResponse(
        context={
            "report": report,
            "selected_period": selected_period(report, request),
        }
    )
