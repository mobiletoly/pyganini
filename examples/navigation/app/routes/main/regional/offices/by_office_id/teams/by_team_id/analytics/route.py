from pyganini import (
    Navigation,
    current_nav_step,
    mount_route,
    nav,
    nav_step,
    route_mount,
    to,
)
from starlette.requests import Request

from app._pyganini.urls import mount_urls, urls
from app.mounts.analytics.handlers import AnalyticsKit, AnalyticsURLs
from app.presentation import regional_office, regional_team, root_path
from app.store import STORE, Customer


def create_regional_analytics(request: Request) -> AnalyticsKit:
    app_urls = urls.with_base_path(root_path(request))
    office_identifier = request.path_params.get("office_id", "")
    team_identifier = request.path_params.get("team_id", "")
    owner_urls = (
        app_urls.main.regional.offices.by_office_id(office_identifier)
        .teams.by_team_id(team_identifier)
        .analytics
    )
    source_urls = mount_urls.analytics.bind(owner_urls)
    office = regional_office(request)
    team = None if office is None else regional_team(request, office)
    request_navigation = nav(request)
    if office is not None and team is not None:
        request_navigation.resolve("office", office.name)
        request_navigation.resolve("team", team.name)
    navigation = request_navigation.navigation()
    risk = request.query_params.get("risk", "")
    page_value = request.query_params.get("page", "1")
    customers = () if team is None else STORE.team_customers(team.identifier)
    if risk:
        customers = tuple(customer for customer in customers if customer.risk == risk)
    customer_identifier = request.path_params.get("customer_id", "")
    selected_customer = next(
        (
            customer
            for customer in customers
            if customer.identifier == customer_identifier
        ),
        None,
    )

    def customer_url(identifier: str) -> str:
        return (
            app_urls.main.regional.offices.by_office_id(office_identifier)
            .teams.by_team_id(team_identifier)
            .customers.by_customer_id(identifier)
            .path
        )

    def customer_report_href(source_navigation: Navigation, identifier: str) -> str:
        return owner_urls.destinations.customer_report(
            office_identifier,
            team_identifier,
            identifier,
        ).navigation_href(source_navigation)

    def report_navigation(report_request: Request, customer: Customer) -> Navigation:
        selected_office = office
        selected_team = team
        if selected_office is None or selected_team is None:
            return Navigation()
        office_urls = app_urls.main.regional.offices.by_office_id(
            selected_office.identifier
        )
        team_urls = office_urls.teams.by_team_id(selected_team.identifier)
        request_navigation = nav(report_request)
        if (
            request_navigation.trail_key()
            != owner_urls.customers.by_customer_id.report.trail_keys.regional_analytics
        ):
            return request_navigation.navigation()
        return request_navigation.navigation_with_trail(
            (
                nav_step("Home", app_urls.root.path),
                nav_step("Main", app_urls.main.path),
                nav_step("Regional", app_urls.main.regional.path),
                nav_step(selected_office.name, office_urls.path),
                nav_step(selected_team.name, team_urls.path),
                nav_step("Analytics", source_urls.path),
                nav_step(customer.name, customer_url(customer.identifier)),
                current_nav_step("Report"),
            )
        )

    problem = "Office" if office is None else "Team" if team is None else None
    return AnalyticsKit(
        navigation=navigation,
        heading="Regional Analytics",
        office=office,
        team=team,
        customers=customers,
        selected_risk=risk,
        selected_page=page_value,
        selected_customer=selected_customer,
        urls=AnalyticsURLs(page_url=source_urls.path),
        customer_url=customer_url,
        customer_report_href=customer_report_href,
        report_navigation=report_navigation,
        problem=problem,
    )


Route = route_mount(
    create=create_regional_analytics,
    mount="analytics",
    routes=(
        mount_route(
            "/",
            destinations=(
                to(
                    "customer-report",
                    urls.main.regional.offices.by_office_id.teams.by_team_id.analytics.customers.by_customer_id.report,
                    trail_key="regional-analytics",
                ),
            ),
        ),
        mount_route("/customers/{customer_id}/report"),
    ),
)
