from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import BaseRoute, Route, Router

from foundation_probes.graph import SYNTHETIC_GRAPH, GraphRoute

SurfaceKind = Literal["router", "application"]


def effective_path(request: Request, local_path: str) -> str:
    """Join an ASGI root path with a graph-local path exactly once."""
    root_path = request.scope.get("root_path", "").rstrip("/")
    normalized = "/" + local_path.lstrip("/")
    return f"{root_path}{normalized}"


async def _home(request: Request, _: GraphRoute) -> HTMLResponse:
    return HTMLResponse(
        f"home|root={request.scope.get('root_path', '')}|"
        f"state={request.scope.get('state', {}).get('outer', 'missing')}"
    )


async def _user(request: Request, route: GraphRoute) -> HTMLResponse:
    user_id = int(request.path_params["user_id"])
    local_path = route.path.replace("{user_id:int}", str(user_id))
    return HTMLResponse(
        f"user={user_id}|effective={effective_path(request, local_path)}|"
        f"state={request.scope.get('state', {}).get('outer', 'missing')}"
    )


ProbeEndpoint = Callable[[Request, GraphRoute], Awaitable[HTMLResponse]]


ENDPOINTS: dict[str, ProbeEndpoint] = {
    "home": _home,
    "user": _user,
}


def _bind_endpoint(route: GraphRoute) -> Callable[[Request], Awaitable[HTMLResponse]]:
    endpoint = ENDPOINTS[route.endpoint]

    async def bound(request: Request) -> HTMLResponse:
        return await endpoint(request, route)

    return bound


def routes_from_graph(graph: Sequence[GraphRoute] = SYNTHETIC_GRAPH) -> list[BaseRoute]:
    return [
        Route(route.path, _bind_endpoint(route), name=route.name) for route in graph
    ]


def build_surface(kind: SurfaceKind) -> Router | Starlette:
    routes = routes_from_graph()
    if kind == "router":
        return Router(routes=routes)
    return Starlette(routes=routes)


class OuterStateMiddleware:
    def __init__(self, app: Any, value: str = "host") -> None:
        self.app = app
        self.value = value

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope["type"] == "http":
            state = dict(scope.get("state", {}))
            state["outer"] = self.value
            scope = {**scope, "state": state}
        await self.app(scope, receive, send)
