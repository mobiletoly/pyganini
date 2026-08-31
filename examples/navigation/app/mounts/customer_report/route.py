from pyganini import RouteNav, route_kit

from .handlers import page

Route = route_kit(
    page=page,
    template="page.jinja",
    nav=RouteNav(label="Report"),
)
