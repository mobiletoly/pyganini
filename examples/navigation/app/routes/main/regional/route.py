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
        {"office_url": app_urls.main.regional.offices.by_office_id("sea").path},
        title="Regional - Pyganini Navigation",
        description="Regional route hierarchy.",
    )


Route = route(page=page, template="page.jinja", nav=RouteNav(label="Regional"))
