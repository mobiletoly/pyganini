from probe_syntax import route


def page() -> None:
    pass


ROUTE = route(path="/same", page=page, metadata={"z": "last", "a": "first"})
