"""HTTP and generated-route behavior for the Chat example."""

from __future__ import annotations

import inspect
from pathlib import Path

from pyganini import browser

from app.routes.chat.handlers import post_message

from .client import ExampleClient


def test_join_validation_cookie_and_redirect(client: ExampleClient) -> None:
    invalid = client.post("/join", data={"name": "   "}, follow_redirects=False)
    assert invalid.status_code == 422
    assert "Enter your name." in invalid.text
    assert "set-cookie" not in invalid.headers

    accepted = client.post(
        "/join", data={"name": "  Ada Lovelace  "}, follow_redirects=False
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/chat"
    cookie = accepted.headers["set-cookie"]
    assert "pyganini_chat_name=Ada%20Lovelace" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie


def test_chat_page_uses_generated_urls_and_visible_htmx(client: ExampleClient) -> None:
    missing_name = client.get("/chat")
    assert 'href="/"' in missing_name.text

    client.post("/join", data={"name": "Ada"})
    page = client.get("/chat")

    assert page.status_code == 200
    assert "Joined as <strong>Ada</strong>" in page.text
    assert 'hx-sse:connect="/chat/events"' in page.text
    assert 'pyganini-sse-event="chat-message"' in page.text
    assert 'hx-swap="beforeend scroll:bottom"' in page.text
    assert 'hx-post="/chat/message"' in page.text
    assert 'hx-target="#composer"' in page.text
    assert 'hx-indicator="#send-progress"' in page.text
    assert 'action="/chat/sign-out"' in page.text


def test_message_validation_authorization_and_publish(client: ExampleClient) -> None:
    unauthorized = client.post("/chat/message", data={"body": "Hello"})
    assert unauthorized.status_code == 401

    client.post("/join", data={"name": "Ada"})
    invalid = client.post("/chat/message", data={"body": "   "})
    assert invalid.status_code == 422
    assert "Enter a message." in invalid.text

    too_long = client.post("/chat/message", data={"body": "x" * 2_001})
    assert too_long.status_code == 422
    assert "Use 2000 characters or fewer." in too_long.text

    accepted = client.post("/chat/message", data={"body": "  Hello, Grace  "})
    assert accepted.status_code == 200
    assert 'value="Hello, Grace"' not in accepted.text

    page = client.get("/chat")
    assert "Hello, Grace" in page.text
    assert page.text.count('class="message"') == 1


def test_message_action_uses_direct_async_capture() -> None:
    assert inspect.iscoroutinefunction(post_message)
    source = (
        Path(__file__).parents[1] / "app" / "routes" / "chat" / "handlers.py"
    ).read_text(encoding="ascii")
    assert "run_coroutine_threadsafe" not in source
    assert "time.sleep" not in source
    assert "await room(request).publish(name, body)" in source


def test_sign_out_clears_cookie(client: ExampleClient) -> None:
    client.post("/join", data={"name": "Ada"})
    response = client.post("/chat/sign-out", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert "pyganini_chat_name=" in cookie
    assert "Max-Age=0" in cookie


def test_local_assets_and_browser_helper_are_served(client: ExampleClient) -> None:
    root = client.get("/")
    helper = client.get(f"/pyganini{browser.SSE_EVENT_HELPER_PATH}")

    assert "/assets/app.2ca0c582.css" in root.text
    assert "/assets/vendor/htmx.min.28fae7bb.js" in root.text
    assert "/assets/vendor/hx-sse.min.d3aeb710.js" in root.text
    assert f"/pyganini{browser.SSE_EVENT_HELPER_PATH}" in root.text
    assert "https://" not in root.text
    assert client.get("/assets/app.2ca0c582.css").status_code == 200
    assert helper.status_code == 200
    assert helper.headers["cache-control"] == "no-cache"
