from pyganini import RouteNav, route_kit

from ..handlers import detailed

Route = route_kit(
    page=detailed,
    template="page.jinja",
    nav=RouteNav(label="Detailed"),
)
