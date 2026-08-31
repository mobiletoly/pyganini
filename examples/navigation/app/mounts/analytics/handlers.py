"""Typed analytics source data and page handler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pyganini import Navigation, Page, PageMetadata
from starlette.requests import Request
from starlette.responses import Response

from app.presentation import layout, not_found
from app.store import Customer, Office, Team


@dataclass(frozen=True, slots=True)
class AnalyticsURLs:
    page_url: str


@dataclass(frozen=True, slots=True)
class AnalyticsKit:
    navigation: Navigation
    heading: str
    office: Office | None
    team: Team | None
    customers: tuple[Customer, ...]
    selected_risk: str
    selected_page: str
    selected_customer: Customer | None
    urls: AnalyticsURLs
    customer_url: Callable[[str], str]
    customer_report_href: Callable[[Navigation, str], str]
    report_navigation: Callable[[Request, Customer], Navigation]
    problem: str | None = None


def page(analytics: AnalyticsKit, request: Request) -> Page | Response:
    if analytics.problem is not None:
        return not_found(analytics.problem)
    return Page(
        context={"analytics": analytics},
        metadata=PageMetadata(
            title=f"{analytics.heading} - Pyganini Navigation",
            description="Filtered customers with generated navigation destinations.",
        ),
        layout=layout(request, analytics.navigation),
    )
