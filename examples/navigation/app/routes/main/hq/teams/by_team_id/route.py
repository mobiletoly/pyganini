from pyganini import RouteNav, nav, route
from starlette.requests import Request

from app._pyganini.urls import urls
from app.presentation import hq_team, not_found, page_response, root_path


def page(request: Request) -> object:
    team = hq_team(request)
    if team is None:
        return not_found("Team")
    request_navigation = nav(request)
    request_navigation.resolve("team", team.name)
    navigation = request_navigation.navigation()
    team_urls = urls.with_base_path(root_path(request)).main.hq.teams.by_team_id(
        team.identifier
    )
    return page_response(
        request,
        navigation,
        {
            "team": team,
            "analytics_url": team_urls.analytics.path,
            "customer_url": team_urls.customers.by_customer_id("contoso").path,
        },
        title=f"{team.name} - Pyganini Navigation",
        description="HQ team routes and destination workflows.",
    )


Route = route(page=page, template="page.jinja", nav=RouteNav(key="team"))
