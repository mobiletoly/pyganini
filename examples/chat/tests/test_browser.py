"""Actual local stable-HTMX named SSE delivery through the Chat application."""

import socket
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from urllib.parse import urlsplit

import uvicorn
from playwright.sync_api import Route, sync_playwright
from starlette.applications import Starlette
from starlette.routing import Mount

from app.main import create_app


@contextmanager
def local_server() -> Generator[str]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    application = Starlette(
        routes=[Mount("/demo", app=create_app(send_delay=0, heartbeat_seconds=0.1))]
    )
    server = uvicorn.Server(
        uvicorn.Config(
            application, log_config=None, access_log=False, log_level="error"
        )
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            server.run(sockets=[listener])
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=run, name="chat-browser-server")
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started and not failures
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive(), "Chat server did not stop"
        if failures:
            raise RuntimeError("Chat server failed") from failures[0]


def test_stable_named_sse_and_validation_under_host_prefix() -> None:
    with local_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        external: list[str] = []
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        origin = urlsplit(base_url)

        def guard(route: Route) -> None:
            target = urlsplit(route.request.url)
            if (target.scheme, target.netloc) == (origin.scheme, origin.netloc):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()

        page.route("**/*", guard)
        try:
            page.goto(base_url + "/demo/")
            assert page.evaluate("window.htmx.version") == "4.0.0"
            page.get_by_label("Name", exact=True).fill("Browser author")
            page.get_by_role("button", name="Enter chat").click()
            page.wait_for_url(base_url + "/demo/chat")
            page.wait_for_function(
                "document.querySelector('#messages').getAttribute('hx-sse:connect').startsWith('/demo/')"
            )
            page.get_by_label("Message", exact=True).fill("Stable named event")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/demo/chat/message")
                    and response.request.method == "POST"
                )
            ) as sent:
                page.get_by_role("button", name="Send", exact=True).click()
            assert sent.value.status == 200
            page.locator("#messages").get_by_text(
                "Stable named event", exact=True
            ).wait_for(timeout=5000)
            assert (
                page.locator("#messages")
                .get_by_text("Stable named event", exact=True)
                .count()
                == 1
            )
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/demo/chat/message")
                    and response.request.method == "POST"
                )
            ) as invalid:
                page.get_by_role("button", name="Send", exact=True).click()
            assert invalid.value.status == 422
            page.get_by_text("Enter a message.", exact=True).wait_for(timeout=5000)
            assert external == []
            assert errors == []
        finally:
            page.close()
            browser.close()
