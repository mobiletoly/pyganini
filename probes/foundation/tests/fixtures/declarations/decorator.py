from probe_syntax import route_decorator


@route_decorator("/decorated")
def page() -> None:
    pass
