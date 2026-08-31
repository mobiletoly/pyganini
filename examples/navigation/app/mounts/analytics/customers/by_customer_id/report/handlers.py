from pyganini import Page, PageMetadata
from starlette.requests import Request
from starlette.responses import Response

from app.mounts.analytics.handlers import AnalyticsKit
from app.presentation import layout, not_found


def page(analytics: AnalyticsKit, request: Request) -> Page | Response:
    if analytics.problem is not None or analytics.team is None:
        return not_found(analytics.problem or "Team")
    customer = analytics.selected_customer
    if customer is None:
        return not_found("Customer")
    navigation = analytics.report_navigation(request, customer)
    return Page(
        context={"analytics": analytics, "customer": customer},
        metadata=PageMetadata(
            title=f"{customer.name} Analytics Report",
            description="Destination-selected analytics report trail.",
        ),
        layout=layout(request, navigation),
    )
