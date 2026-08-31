from pyganini import Page, RouteNav, nav, route
from starlette.requests import Request

from app.presentation import page_response


def page(request: Request) -> Page:
    navigation = nav(request).navigation()
    return page_response(
        request,
        navigation,
        {},
        title="About - Pyganini Navigation",
        description="Ownership boundaries used by the Navigation example.",
    )


Route = route(page=page, template="page.jinja", nav=RouteNav(label="About"))
