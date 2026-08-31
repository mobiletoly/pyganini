"""Application-owned Starlette host for the Chat example."""

from __future__ import annotations

from pathlib import Path

from pyganini import browser, create_environment
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app._pyganini.asgi import create_router
from app.events import EVENTS_PATH, create_events_endpoint
from app.room import ChatRoom, Message

ASSET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "dist"


def create_app(
    *,
    send_delay: float = 3.0,
    heartbeat_seconds: float = 20.0,
) -> Starlette:
    if isinstance(send_delay, bool) or send_delay < 0:
        raise ValueError("send_delay must be non-negative")
    if isinstance(heartbeat_seconds, bool) or heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")

    room = ChatRoom()
    environment = create_environment()

    def render_message(message: Message) -> str:
        template = environment.get_template("routes/chat/message.jinja")
        return template.render(message=message)

    application = Starlette(
        routes=[
            Mount(
                "/assets",
                app=StaticFiles(directory=ASSET_DIRECTORY),
                name="assets",
            ),
            Mount("/pyganini", app=browser.create_app(), name="pyganini-browser"),
            Route(
                EVENTS_PATH,
                endpoint=create_events_endpoint(
                    room,
                    render_message,
                    heartbeat_seconds,
                ),
                methods=["GET"],
                name="chat-events",
            ),
            Mount("/", app=create_router(environment=environment)),
        ],
    )
    application.state.room = room
    application.state.send_delay = float(send_delay)
    return application


app: Starlette = create_app()
