from pyganini import RouteNav, kit_fragment_route, route_kit

from .handlers import page, table

Route = route_kit(
    page=page,
    template="page.jinja",
    fragments=(kit_fragment_route("/table", table, template="table.jinja"),),
    nav=RouteNav(label="Reports"),
)
