from pyganini import RouteNav, kit_fragment_route, route_kit, RouteMeta  # noqa: I001

from .handlers import page, table

Route = route_kit(
    page=page,
    template="page.jinja",
    fragments=(kit_fragment_route("/table", table, template="table.jinja"),),
    nav=RouteNav(label="Directory"),
    name="contact-directory",
    title="Contact Directory",
    meta=RouteMeta(
        labels={
            "app.area": "contacts",
            "app.source": "shared-kit",
        }
    ),
)
