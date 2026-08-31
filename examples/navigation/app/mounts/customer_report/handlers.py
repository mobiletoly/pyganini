from dataclasses import dataclass

from pyganini import Navigation, Page, PageMetadata
from starlette.requests import Request
from starlette.responses import Response

from app.presentation import layout, not_found
from app.store import Customer


@dataclass(frozen=True, slots=True)
class CustomerReportURLs:
    page_url: str
    brief_url: str
    detailed_url: str


@dataclass(frozen=True, slots=True)
class CustomerReportKit:
    navigation: Navigation
    customer: Customer | None
    urls: CustomerReportURLs
    problem: str | None = None


def _page(
    report: CustomerReportKit,
    request: Request,
    *,
    title: str,
    description: str,
    view: str,
) -> Page | Response:
    if report.problem is not None or report.customer is None:
        return not_found(report.problem or "Customer")
    return Page(
        context={"report": report, "view": view},
        metadata=PageMetadata(title=title, description=description),
        layout=layout(request, report.navigation),
    )


def page(report: CustomerReportKit, request: Request) -> Page | Response:
    customer_name = report.customer.name if report.customer is not None else "Customer"
    return _page(
        report,
        request,
        title=f"{customer_name} Report",
        description="Mounted customer report overview.",
        view="overview",
    )


def brief(report: CustomerReportKit, request: Request) -> Page | Response:
    customer_name = report.customer.name if report.customer is not None else "Customer"
    return _page(
        report,
        request,
        title=f"{customer_name} Brief Report",
        description="Brief mounted customer report.",
        view="brief",
    )


def detailed(report: CustomerReportKit, request: Request) -> Page | Response:
    customer_name = report.customer.name if report.customer is not None else "Customer"
    return _page(
        report,
        request,
        title=f"{customer_name} Detailed Report",
        description="Detailed mounted customer report.",
        view="detailed",
    )
