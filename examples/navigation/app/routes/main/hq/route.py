from pyganini import Page, RouteNav, nav, route
from starlette.requests import Request

from app._pyganini.urls import urls
from app.presentation import page_response, root_path


def page(request: Request) -> Page:
    app_urls = urls.with_base_path(root_path(request))
    navigation = nav(request).navigation()
    return page_response(
        request,
        navigation,
        {"team_url": app_urls.main.hq.teams.by_team_id("hq-team").path},
        title="HQ - Pyganini Navigation",
        description="HQ route hierarchy.",
    )


Route = route(page=page, template="page.jinja", nav=RouteNav(label="HQ"))
