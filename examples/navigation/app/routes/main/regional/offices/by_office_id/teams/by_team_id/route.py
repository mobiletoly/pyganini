from pyganini import RouteNav, nav, route
from starlette.requests import Request

from app._pyganini.urls import urls
from app.presentation import (
    not_found,
    page_response,
    regional_office,
    regional_team,
    root_path,
)


def page(request: Request) -> object:
    office = regional_office(request)
    if office is None:
        return not_found("Office")
    team = regional_team(request, office)
    if team is None:
        return not_found("Team")
    request_navigation = nav(request)
    request_navigation.resolve("office", office.name)
    request_navigation.resolve("team", team.name)
    navigation = request_navigation.navigation()
    team_urls = (
        urls.with_base_path(root_path(request))
        .main.regional.offices.by_office_id(office.identifier)
        .teams.by_team_id(team.identifier)
    )
    return page_response(
        request,
        navigation,
        {
            "office": office,
            "team": team,
            "analytics_url": team_urls.analytics.path,
            "customer_url": team_urls.customers.by_customer_id("northwind").path,
        },
        title=f"{team.name} - Pyganini Navigation",
        description="Regional team routes and destination workflows.",
    )


Route = route(page=page, template="page.jinja", nav=RouteNav(key="team"))
