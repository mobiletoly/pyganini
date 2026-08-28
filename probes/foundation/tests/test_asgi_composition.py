from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, Router
from starlette.testclient import TestClient

from foundation_probes.asgi_composition import (
    OuterStateMiddleware,
    build_surface,
    routes_from_graph,
)
from foundation_probes.graph import GraphRoute


@pytest.mark.parametrize("kind", ["router", "application"])
def test_router_and_application_can_be_hosted_directly(kind: str) -> None:
    with TestClient(build_surface(kind)) as client:  # type: ignore[arg-type]
        response = client.get("/users/7")
    assert response.status_code == 200
    assert response.text == "user=7|effective=/users/7|state=missing"


def test_router_mounts_under_plain_starlette_with_outer_state() -> None:
    host = Starlette(
        routes=[Mount("/html", app=build_surface("router"))],
        middleware=[Middleware(OuterStateMiddleware, value="starlette")],
    )
    with TestClient(host) as client:
        response = client.get("/html/users/8")
    assert response.text == "user=8|effective=/html/users/8|state=starlette"


def _fastapi_host(*, pyganini_first: bool = False) -> FastAPI:
    host = FastAPI()
    host.add_middleware(OuterStateMiddleware, value="fastapi")
    surface = build_surface("router")
    if pyganini_first:
        host.mount("/", surface, name="html")

    @host.get("/api/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    assert callable(_health)
    if not pyganini_first:
        host.mount("/", surface, name="html")
    return host


def test_fastapi_specific_route_precedes_root_mount_and_owns_openapi() -> None:
    host = _fastapi_host()
    with TestClient(host) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        html = client.get("/users/3")
        assert html.status_code == 200
        assert "state=fastapi" in html.text
        schema = client.get("/openapi.json").json()
    assert "/api/health" in schema["paths"]
    assert "/users/{user_id}" not in schema["paths"]


def test_reversed_root_mount_order_hides_specific_fastapi_route() -> None:
    host = _fastapi_host(pyganini_first=True)
    with TestClient(host) as client:
        response = client.get("/api/health")
    assert response.status_code == 404


def test_proxy_root_and_mount_prefix_are_included_once() -> None:
    host = Starlette(routes=[Mount("/html", app=build_surface("router"))])
    with TestClient(
        host,
        base_url="http://testserver/proxy",
        root_path="/proxy",
    ) as client:
        response = client.get("/html/users/11")
    assert response.status_code == 200
    assert "effective=/proxy/html/users/11" in response.text


def test_fastapi_prefix_mount_honors_proxy_root_without_openapi_leak() -> None:
    host = FastAPI()
    host.mount("/html", build_surface("router"), name="html")
    with TestClient(
        host,
        base_url="http://testserver/proxy",
        root_path="/proxy",
    ) as client:
        response = client.get("/html/users/12")
        schema = client.get("/openapi.json").json()
    assert response.status_code == 200
    assert "effective=/proxy/html/users/12" in response.text
    assert "/users/{user_id}" not in schema["paths"]


def test_graph_local_path_that_repeats_mount_prefix_is_not_deduplicated() -> None:
    graph = (
        GraphRoute(
            name="user",
            path="/html/users/{user_id:int}",
            endpoint="user",
            parameters=(("user_id", int),),
        ),
    )
    host = Starlette(
        routes=[Mount("/html", app=Router(routes=routes_from_graph(graph)))]
    )
    with TestClient(host) as client:
        response = client.get("/html/html/users/13")
    assert response.status_code == 200
    assert "effective=/html/html/users/13" in response.text


def test_host_owns_lifespan_and_surface_needs_none() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    async def status(_: Any) -> JSONResponse:
        return JSONResponse({"events": list(events)})

    host = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/host-status", status),
            Mount("/", app=build_surface("router")),
        ],
    )
    with TestClient(host) as client:
        assert client.get("/host-status").json() == {"events": ["startup"]}
        assert client.get("/").status_code == 200
    assert events == ["startup", "shutdown"]
