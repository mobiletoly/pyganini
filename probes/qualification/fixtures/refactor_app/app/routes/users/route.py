from pyganini import action, fragment_route, route

from .handlers import page, save, table

Route = route(
    page=page,
    template="page.jinja",
    fragments=(fragment_route("/table", table, template="table.jinja"),),
    actions=(action("POST", "/save", save),),
)
