from pyganini import nav, route_mount
from starlette.requests import Request

from app._pyganini.urls import mount_urls, urls
from app.mounts.customer_report.handlers import (
    CustomerReportKit,
    CustomerReportURLs,
)
from app.presentation import hq_team, owned_customer, root_path


def create_hq_customer_report(request: Request) -> CustomerReportKit:
    app_urls = urls.with_base_path(root_path(request))
    team_identifier = request.path_params.get("team_id", "")
    customer_identifier = request.path_params.get("customer_id", "")
    owner_urls = (
        app_urls.main.hq.teams.by_team_id(team_identifier)
        .customers.by_customer_id(customer_identifier)
        .report
    )
    source_urls = mount_urls.customer_report.bind(owner_urls)
    team = hq_team(request)
    customer = None if team is None else owned_customer(request, team)
    request_navigation = nav(request)
    if team is not None and customer is not None:
        request_navigation.resolve("team", team.name)
        request_navigation.resolve("customer", customer.name)
    problem = "Team" if team is None else "Customer" if customer is None else None
    return CustomerReportKit(
        navigation=request_navigation.navigation(),
        customer=customer,
        urls=CustomerReportURLs(
            page_url=source_urls.path,
            brief_url=source_urls.brief.path,
            detailed_url=source_urls.detailed.path,
        ),
        problem=problem,
    )


Route = route_mount(
    create=create_hq_customer_report,
    mount="customer_report",
)
