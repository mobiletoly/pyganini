from pyganini import RouteNav, current_nav_step, nav, nav_step, route
from starlette.requests import Request

from app._pyganini.urls import urls
from app.presentation import not_found, page_response, root_path
from app.store import STORE


def page(request: Request) -> object:
    customer = STORE.customer(request.path_params.get("customer_id", ""))
    if customer is None:
        return not_found("Customer")
    team = STORE.team(customer.team_identifier)
    if team is None:
        return not_found("Team")
    app_urls = urls.with_base_path(root_path(request))
    request_navigation = nav(request)
    navigation = request_navigation.navigation()
    trail_kind = "canonical"
    if (
        request_navigation.trail_key()
        == app_urls.main.reports.by_customer_id.trail_keys.hq_customer
        and team.office_identifier is None
    ):
        team_urls = app_urls.main.hq.teams.by_team_id(team.identifier)
        navigation = request_navigation.navigation_with_trail(
            (
                nav_step("Home", app_urls.root.path),
                nav_step("Main", app_urls.main.path),
                nav_step("HQ", app_urls.main.hq.path),
                nav_step(team.name, team_urls.path),
                nav_step(
                    customer.name,
                    team_urls.customers.by_customer_id(customer.identifier).path,
                ),
                current_nav_step("Report"),
            )
        )
        trail_kind = "hq-customer"
    elif (
        request_navigation.trail_key()
        == app_urls.main.reports.by_customer_id.trail_keys.regional_customer
        and team.office_identifier is not None
    ):
        office = STORE.office(team.office_identifier)
        if office is None:
            return not_found("Office")
        office_urls = app_urls.main.regional.offices.by_office_id(office.identifier)
        regional_team_urls = office_urls.teams.by_team_id(team.identifier)
        navigation = request_navigation.navigation_with_trail(
            (
                nav_step("Home", app_urls.root.path),
                nav_step("Main", app_urls.main.path),
                nav_step("Regional", app_urls.main.regional.path),
                nav_step(office.name, office_urls.path),
                nav_step(team.name, regional_team_urls.path),
                nav_step(
                    customer.name,
                    regional_team_urls.customers.by_customer_id(
                        customer.identifier
                    ).path,
                ),
                current_nav_step("Report"),
            )
        )
        trail_kind = "regional-customer"
    return page_response(
        request,
        navigation,
        {"customer": customer, "trail_kind": trail_kind},
        title=f"{customer.name} Shared Report",
        description="Shared destination with an entry-specific navigation trail.",
    )


Route = route(
    page=page,
    template="page.jinja",
    nav=RouteNav(label="Report"),
)
