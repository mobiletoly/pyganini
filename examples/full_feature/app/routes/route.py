from pyganini import RouteMeta, RouteNav, route

from .handlers import page

Route = route(
    page=page,
    template="page.jinja",
    nav=RouteNav(label="Home"),
    error_page_template="error_page.jinja",
    error_fragment_template="error_fragment.jinja",
    name="home",
    title="Pyganini Full Feature",
    meta=RouteMeta(
        labels={
            "app.area": "home",
            "app.visibility": "public",
        }
    ),
)
