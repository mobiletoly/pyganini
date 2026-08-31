from pyganini import RouteNav, nav, route
from starlette.requests import Request

from app._pyganini.urls import urls
from app.presentation import not_found, page_response, regional_office, root_path


def page(request: Request) -> object:
    office = regional_office(request)
    if office is None:
        return not_found("Office")
    request_navigation = nav(request)
    request_navigation.resolve("office", office.name)
    navigation = request_navigation.navigation()
    office_urls = urls.with_base_path(
        root_path(request)
    ).main.regional.offices.by_office_id(office.identifier)
    return page_response(
        request,
        navigation,
        {
            "office": office,
            "team_url": office_urls.teams.by_team_id("regional-team").path,
        },
        title=f"{office.name} - Pyganini Navigation",
        description="Regional office route with a dynamic label.",
    )


Route = route(page=page, template="page.jinja", nav=RouteNav(key="office"))
