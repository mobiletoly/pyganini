"""Root page and one declared precedence proof."""

from pyganini import fragment_route, route

from .handlers import declared, page

Route = route(
    page=page,
    template="page.jinja",
    error_page_template="error_page.jinja",
    fragments=(fragment_route("/declared", declared),),
)
