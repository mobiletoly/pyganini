from probe_syntax import route

PREFIX = "/computed"


def page() -> None:
    pass


ROUTE = route(path=PREFIX + "/value", page=page)
