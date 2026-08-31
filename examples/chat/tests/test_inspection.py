"""Generated and source-level Chat example boundaries."""

from pathlib import Path

from app._pyganini.urls import urls


def test_generated_url_surface_matches_chat_routes() -> None:
    assert urls.root.path == "/"
    assert urls.join.path == "/join"
    assert urls.chat.path == "/chat"
    assert urls.chat.message.path == "/chat/message"
    assert urls.chat.sign_out.path == "/chat/sign-out"


def test_templates_keep_chat_hypermedia_visible() -> None:
    route = Path(__file__).parents[1] / "app" / "routes" / "chat"
    page = (route / "page.jinja").read_text(encoding="ascii")
    composer = (route / "composer.jinja").read_text(encoding="ascii")

    assert 'hx-sse:connect="{{ events_url }}"' in page
    assert 'pyganini-sse-event="chat-message"' in page
    assert 'hx-post="{{ message_url }}"' in composer
    assert 'hx-indicator="#send-progress"' in composer
