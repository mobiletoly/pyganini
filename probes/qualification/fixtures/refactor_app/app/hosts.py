from __future__ import annotations

from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app._pyganini.asgi import create_router


async def health(_: object) -> JSONResponse:
    return JSONResponse({"status": "ok"})


starlette_host = Starlette(
    routes=[Route("/health", health), Mount("/", app=create_router())]
)

fastapi_host = FastAPI()
fastapi_host.add_api_route("/api/health", lambda: {"status": "ok"})
fastapi_host.mount("/html", create_router())
