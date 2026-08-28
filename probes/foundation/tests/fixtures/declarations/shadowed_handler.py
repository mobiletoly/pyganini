from collections.abc import Callable

from fragments import summary as page
from probe_syntax import route


def build_page() -> Callable[[], None]:
    return lambda: None


page = build_page()  # noqa: F811

ROUTE = route(path="/shadowed", page=page)
