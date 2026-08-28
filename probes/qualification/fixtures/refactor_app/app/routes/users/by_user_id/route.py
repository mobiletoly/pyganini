from pyganini import route

from .handlers import page

Route = route(page=page, template="page.jinja")
