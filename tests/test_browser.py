from __future__ import annotations

import hashlib
from importlib import resources
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

import pyganini
from pyganini import browser

HELPER_BYTES = b"""(function () {
  if (!window.htmx || !window.htmx.registerExtension) {
    return;
  }

  window.htmx.registerExtension("pyganini-sse-event", {
    htmx_before_sse_message: function (element, detail) {
      if (!element || !detail || !detail.message) {
        return;
      }

      var eventName = detail.message.event;
      if (!eventName) {
        return;
      }

      var swapEvent = element.getAttribute("pyganini-sse-event");
      if (!swapEvent) {
        return;
      }

      if (eventName === swapEvent.trim()) {
        detail.message.event = "";
      }
    }
  });
})();
"""
ETAG = '"beaea931c38ac5c67f07ebe787bccd96ec4a7a0f85176103a58f41370de24941"'
TEMPLATE_INSPECTOR_ETAG = (
    '"8229d016bc7d4b2f74acab19fa75019a83cd0128988302ca1ccc53c803daba59"'
)
TEMPLATE_INSPECTOR_BYTES = (
    resources.files("pyganini.browser")
    .joinpath("pyganini-template-inspector.js")
    .read_bytes()
)
RESOURCE_CASES = (
    pytest.param(browser.SSE_EVENT_HELPER_PATH, HELPER_BYTES, ETAG, id="sse-event"),
    pytest.param(
        browser.TEMPLATE_INSPECTOR_HELPER_PATH,
        TEMPLATE_INSPECTOR_BYTES,
        TEMPLATE_INSPECTOR_ETAG,
        id="template-inspector",
    ),
)


def test_public_surface_and_exact_helper_bytes() -> None:
    assert pyganini.browser is browser
    assert browser.SSE_EVENT_HELPER_PATH == "/pyganini-sse-event.js"
    assert browser.SSE_EVENT_EXTENSION_NAME == "pyganini-sse-event"
    assert browser.SSE_EVENT_ATTRIBUTE == "pyganini-sse-event"
    assert set(browser.__all__) == {
        "SSE_EVENT_ATTRIBUTE",
        "SSE_EVENT_EXTENSION_NAME",
        "SSE_EVENT_HELPER_PATH",
        "TEMPLATE_INSPECTOR_HELPER_PATH",
        "create_app",
    }
    assert "browser" in pyganini.__all__
    assert not hasattr(pyganini, "SSE_EVENT_HELPER_PATH")
    assert not hasattr(pyganini, "create_app")

    with TestClient(browser.create_app()) as client:
        body = client.get(browser.SSE_EVENT_HELPER_PATH).content
    assert body == HELPER_BYTES
    assert hashlib.sha256(body).hexdigest() == ETAG.strip('"')


def test_template_inspector_resource_has_exact_identity() -> None:
    assert browser.TEMPLATE_INSPECTOR_HELPER_PATH == "/pyganini-template-inspector.js"
    assert "TEMPLATE_INSPECTOR_HELPER_PATH" in browser.__all__
    assert TEMPLATE_INSPECTOR_BYTES.endswith(b"\n")
    assert TEMPLATE_INSPECTOR_BYTES.decode("ascii").startswith("(function () {\n")
    assert hashlib.sha256(
        TEMPLATE_INSPECTOR_BYTES
    ).hexdigest() == TEMPLATE_INSPECTOR_ETAG.strip('"')


@pytest.mark.parametrize(("path", "body", "etag"), RESOURCE_CASES)
def test_get_head_and_conditional_contract(
    path: str,
    body: bytes,
    etag: str,
) -> None:
    with TestClient(browser.create_app()) as client:
        get = client.get(path)
        head = client.head(path)

        assert get.status_code == head.status_code == 200
        assert get.content == body
        assert head.content == b""
        for response in (get, head):
            assert response.headers["content-type"] == (
                "text/javascript; charset=utf-8"
            )
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["etag"] == etag
            assert response.headers["content-length"] == str(len(body))
            assert "last-modified" not in response.headers
            assert "accept-ranges" not in response.headers

        for validator in (etag, f"W/{etag}", "*", f'"other", W/{etag}'):
            for method in (client.get, client.head):
                response = method(
                    path,
                    headers={"If-None-Match": f" \t{validator}\t "},
                )
                assert response.status_code == 304
                assert response.content == b""
                assert response.headers["etag"] == etag
                assert response.headers["cache-control"] == "no-cache"
                assert response.headers["content-type"] == (
                    "text/javascript; charset=utf-8"
                )
                assert "content-length" not in response.headers
                assert "last-modified" not in response.headers


@pytest.mark.parametrize(("path", "body", "etag"), RESOURCE_CASES)
def test_nonmatching_and_malformed_validators_return_full_body(
    path: str,
    body: bytes,
    etag: str,
) -> None:
    with TestClient(browser.create_app()) as client:
        for validator in (
            "",
            '"other"',
            f"w/{etag}",
            etag.upper(),
            etag.strip('"'),
            f"W/ {etag}",
            '"broken',
            f'"other", w/{etag}',
        ):
            response = client.get(path, headers={"If-None-Match": validator})
            assert response.status_code == 200
            assert response.content == body


@pytest.mark.parametrize(("path", "body", "etag"), RESOURCE_CASES)
def test_methods_and_ignored_range_headers(
    path: str,
    body: bytes,
    etag: str,
) -> None:
    with TestClient(browser.create_app()) as client:
        for method_name in ("POST", "PROPFIND"):
            method = client.request(method_name, path)
            assert method.status_code == 405
            assert method.content == b"Method Not Allowed"
            assert method.headers["allow"] == "GET, HEAD"
            assert method.headers["content-type"] == "text/plain; charset=utf-8"
            assert method.headers["content-length"] == "18"

        ranged = client.get(
            path,
            headers={
                "Range": "bytes=0-5",
                "If-Range": etag,
                "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT",
            },
        )
        assert ranged.status_code == 200
        assert ranged.content == body
        assert "content-range" not in ranged.headers

        conditional_range = client.get(
            path,
            headers={"Range": "bytes=0-5", "If-None-Match": etag},
        )
        assert conditional_range.status_code == 304


def test_unknown_paths_have_exact_failure() -> None:
    with TestClient(browser.create_app()) as client:
        for path in (
            "/",
            "/pyganini-sse-event.js/",
            "/PYGANINI-sse-event.js",
            "/pyganini-template-inspector.js/",
            "/PYGANINI-template-inspector.js",
            "/other.js",
            "/%2e%2e/pyganini-sse-event.js",
        ):
            response = client.get(path)
            assert response.status_code == 404
            assert response.content == b"Not Found"
            assert response.headers["content-type"] == "text/plain; charset=utf-8"
            assert response.headers["content-length"] == "9"
            assert "etag" not in response.headers
            assert "cache-control" not in response.headers


@pytest.mark.parametrize(("path", "body", "etag"), RESOURCE_CASES)
def test_mount_root_path_and_fastapi_host_are_application_owned(
    path: str,
    body: bytes,
    etag: str,
) -> None:
    del etag
    starlette = Starlette(
        routes=[Mount("/helpers", app=browser.create_app(), name="helpers")]
    )
    with TestClient(starlette, root_path="/host") as client:
        response = client.get(f"/host/helpers{path}")
    assert response.status_code == 200
    assert response.content == body

    fastapi = FastAPI()
    fastapi.mount("/helpers", browser.create_app())
    with TestClient(fastapi) as client:
        response = client.get(f"/helpers{path}")
    assert response.status_code == 200
    assert response.content == body


@pytest.mark.parametrize(("path", "body", "etag"), RESOURCE_CASES)
def test_raw_asgi_head_sends_no_body_with_get_representation_length(
    path: str,
    body: bytes,
    etag: str,
) -> None:
    del etag
    app = browser.create_app()
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    async def run() -> None:
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "HEAD",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "root_path": "/host/helpers",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        await app(scope, receive, send)

    import asyncio

    asyncio.run(run())
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    headers = dict(start["headers"])
    bodies = [
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    ]
    assert headers[b"content-length"] == str(len(body)).encode("ascii")
    assert b"".join(bodies) == b""


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        (
            "pyganini-sse-event.js",
            r"^pyganini browser helper resource unavailable: pyganini-sse-event\.js$",
        ),
        (
            "pyganini-template-inspector.js",
            r"^pyganini browser helper resource unavailable: "
            r"pyganini-template-inspector\.js$",
        ),
    ],
)
def test_missing_required_resource_has_exact_failure(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    message: str,
) -> None:
    available = browser.resources.files("pyganini.browser")

    class MissingResource:
        def joinpath(self, name: str) -> Any:
            if name == missing:
                raise FileNotFoundError
            return available.joinpath(name)

    def unavailable(_package: str) -> MissingResource:
        return MissingResource()

    monkeypatch.setattr(browser.resources, "files", unavailable)
    with pytest.raises(
        RuntimeError,
        match=message,
    ):
        browser.create_app()
