from pyganini import RouteNav, route_kit

from ..handlers import brief

Route = route_kit(
    page=brief,
    template="page.jinja",
    nav=RouteNav(label="Brief"),
)
