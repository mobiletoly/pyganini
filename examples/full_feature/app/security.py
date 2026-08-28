"""Application-owned security-header and route-policy middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ExamplePolicyMiddleware:
    """Apply the example's response security header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message["headers"],
                        (b"x-content-type-options", b"nosniff"),
                    ],
                }
            await send(message)

        await self.app(scope, receive, send_wrapper)


class ImmutableAssetCacheMiddleware:
    """Apply immutable caching only inside the fingerprinted asset mount."""

    def __init__(self, app: ASGIApp, *, fingerprinted_paths: Iterable[str]) -> None:
        self.app = app
        self._fingerprinted_paths = frozenset(fingerprinted_paths)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status = message["status"]
                path = scope.get("path")
                root_path = scope.get("root_path")
                relative_path = ""
                if isinstance(path, str) and isinstance(root_path, str):
                    if root_path and path.startswith(root_path + "/"):
                        relative_path = path[len(root_path) + 1 :]
                    else:
                        relative_path = path.removeprefix("/")
                if (
                    status in {200, 206, 304}
                    and relative_path in self._fingerprinted_paths
                ):
                    headers = [
                        (name, value)
                        for name, value in message["headers"]
                        if name.lower() != b"cache-control"
                    ]
                    headers.append(
                        (
                            b"cache-control",
                            b"public, max-age=31536000, immutable",
                        )
                    )
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class ExampleRoutePolicyMiddleware(BaseHTTPMiddleware):
    """Expose the live route owner's example policy to request handlers."""

    def __init__(self, app: ASGIApp, policy: str) -> None:
        super().__init__(app)
        self._policy = policy

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.route_policy = self._policy
        return await call_next(request)
