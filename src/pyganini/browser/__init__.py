"""Fixed browser-helper resources for explicit application mounting."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources
from typing import Final

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

SSE_EVENT_HELPER_PATH: Final = "/pyganini-sse-event.js"
TEMPLATE_INSPECTOR_HELPER_PATH: Final = "/pyganini-template-inspector.js"
SSE_EVENT_EXTENSION_NAME: Final = "pyganini-sse-event"
SSE_EVENT_ATTRIBUTE: Final = "pyganini-sse-event"

_SSE_EVENT_HELPER_NAME = SSE_EVENT_HELPER_PATH.removeprefix("/")
_TEMPLATE_INSPECTOR_HELPER_NAME = TEMPLATE_INSPECTOR_HELPER_PATH.removeprefix("/")
_CONTENT_TYPE = "text/javascript; charset=utf-8"
_CACHE_CONTROL = "no-cache"

__all__ = [
    "SSE_EVENT_ATTRIBUTE",
    "SSE_EVENT_EXTENSION_NAME",
    "SSE_EVENT_HELPER_PATH",
    "TEMPLATE_INSPECTOR_HELPER_PATH",
    "create_app",
]


@dataclass(frozen=True, slots=True)
class _Helper:
    content: bytes
    etag: str


class _HelperResponse:
    def __init__(
        self,
        *,
        status: int,
        headers: tuple[tuple[bytes, bytes], ...],
        body: bytes = b"",
        head: bool = False,
    ) -> None:
        self._status = status
        self._headers = headers
        self._body = body
        self._head = head

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, receive
        start: Message = {
            "type": "http.response.start",
            "status": self._status,
            "headers": list(self._headers),
        }
        await send(start)
        body: Message = {
            "type": "http.response.body",
            "body": b"" if self._head else self._body,
        }
        await send(body)


def _load_helpers() -> dict[str, _Helper]:
    helpers: dict[str, _Helper] = {}
    for name in (_SSE_EVENT_HELPER_NAME, _TEMPLATE_INSPECTOR_HELPER_NAME):
        try:
            content = resources.files("pyganini.browser").joinpath(name).read_bytes()
        except OSError as error:
            raise RuntimeError(
                f"pyganini browser helper resource unavailable: {name}"
            ) from error
        digest = hashlib.sha256(content).hexdigest()
        helpers[name] = _Helper(content, f'"{digest}"')
    return helpers


def _etag_matches(value: str, etag: str) -> bool:
    return any(
        candidate in {"*", etag, f"W/{etag}"}
        for candidate in (item.strip(" \t") for item in value.split(","))
    )


def _representation_headers(helper: _Helper) -> tuple[tuple[bytes, bytes], ...]:
    return (
        (b"content-type", _CONTENT_TYPE.encode("ascii")),
        (b"cache-control", _CACHE_CONTROL.encode("ascii")),
        (b"etag", helper.etag.encode("ascii")),
    )


class _HelperEndpoint:
    def __init__(self, helpers: dict[str, _Helper]) -> None:
        self._helpers = helpers

    def _response(self, request: Request) -> _HelperResponse:
        if request.method not in {"GET", "HEAD"}:
            return _HelperResponse(
                status=405,
                headers=(
                    (b"allow", b"GET, HEAD"),
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", b"18"),
                ),
                body=b"Method Not Allowed",
            )

        helper = self._helpers.get(request.path_params["path"])
        if helper is None:
            return _HelperResponse(
                status=404,
                headers=(
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", b"9"),
                ),
                body=b"Not Found",
                head=request.method == "HEAD",
            )

        representation_headers = _representation_headers(helper)
        if _etag_matches(request.headers.get("If-None-Match", ""), helper.etag):
            return _HelperResponse(status=304, headers=representation_headers)

        return _HelperResponse(
            status=200,
            headers=(
                *representation_headers,
                (b"content-length", str(len(helper.content)).encode("ascii")),
            ),
            body=helper.content,
            head=request.method == "HEAD",
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = self._response(Request(scope, receive=receive))
        await response(scope, receive, send)


def create_app() -> Starlette:
    """Create a fixed-resource Starlette app for explicit host mounting."""
    return Starlette(
        routes=[
            Route(
                "/{path:path}",
                endpoint=_HelperEndpoint(_load_helpers()),
            )
        ]
    )
