from probe_syntax import route

from .handlers import page as handler

ROUTE = route(path="/relative", page=handler)
