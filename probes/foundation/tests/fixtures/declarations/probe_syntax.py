from collections.abc import Callable
from typing import Any


class RouteValue:
    pass


def route(**_: object) -> RouteValue:
    return RouteValue()


def route_decorator(_: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        return function

    return decorate
