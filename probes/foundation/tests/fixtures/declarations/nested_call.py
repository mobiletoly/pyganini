from collections.abc import Callable

from probe_syntax import route


def make_handler() -> Callable[[], None]:
    return lambda: None


ROUTE = route(path="/nested", page=make_handler())
