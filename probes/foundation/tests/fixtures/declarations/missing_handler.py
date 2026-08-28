from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from probe_syntax import route

if TYPE_CHECKING:
    missing_handler = cast("Callable[[], None]", None)

ROUTE = route(path="/missing", page=missing_handler)
