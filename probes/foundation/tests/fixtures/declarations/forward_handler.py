from probe_syntax import route

ROUTE = route(path="/forward", page=page)  # type: ignore[used-before-def]


def page() -> None:
    pass
