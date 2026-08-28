"""Application-owned immutable asset caching."""

from __future__ import annotations

from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ImmutableAssetCacheMiddleware:
    """Cache successful responses only for generated fingerprinted files."""

    def __init__(self, app: ASGIApp, *, fingerprinted_paths: Iterable[str]) -> None:
        self.app = app
        self._fingerprinted_paths = frozenset(fingerprinted_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                path = scope.get("path")
                root_path = scope.get("root_path")
                relative_path = ""
                if isinstance(path, str) and isinstance(root_path, str):
                    if root_path and path.startswith(root_path + "/"):
                        relative_path = path[len(root_path) + 1 :]
                    else:
                        relative_path = path.removeprefix("/")
                if (
                    message["status"] in {200, 206, 304}
                    and relative_path in self._fingerprinted_paths
                ):
                    headers = [
                        (name, value)
                        for name, value in message["headers"]
                        if name.lower() != b"cache-control"
                    ]
                    message = {
                        **message,
                        "headers": [
                            *headers,
                            (
                                b"cache-control",
                                b"public, max-age=31536000, immutable",
                            ),
                        ],
                    }
            await send(message)

        await self.app(scope, receive, send_wrapper)
