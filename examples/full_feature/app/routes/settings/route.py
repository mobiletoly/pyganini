from pyganini import RouteNav, route

from .handlers import page

Route = route(page=page, template="page.jinja", nav=RouteNav(label="Settings"))
