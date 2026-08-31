from pyganini import RouteNav, nav, route, to
from starlette.requests import Request

from app._pyganini.urls import urls
from app.presentation import (
    hq_team,
    not_found,
    owned_customer,
    page_response,
    root_path,
)


def page(request: Request) -> object:
    team = hq_team(request)
    if team is None:
        return not_found("Team")
    customer = owned_customer(request, team)
    if customer is None:
        return not_found("Customer")
    request_navigation = nav(request)
    request_navigation.resolve("team", team.name)
    request_navigation.resolve("customer", customer.name)
    navigation = request_navigation.navigation()
    customer_urls = (
        urls.with_base_path(root_path(request))
        .main.hq.teams.by_team_id(team.identifier)
        .customers.by_customer_id(customer.identifier)
    )
    return page_response(
        request,
        navigation,
        {
            "customer": customer,
            "local_report_url": customer_urls.report.path,
            "shared_report_url": customer_urls.destinations.shared_report(
                customer.identifier
            ).navigation_href(navigation),
        },
        title=f"{customer.name} - Pyganini Navigation",
        description="HQ customer route with local and shared reports.",
    )


Route = route(
    page=page,
    template="page.jinja",
    nav=RouteNav(key="customer"),
    destinations=(
        to(
            "shared-report",
            urls.main.reports.by_customer_id,
            trail_key="hq-customer",
        ),
    ),
)
