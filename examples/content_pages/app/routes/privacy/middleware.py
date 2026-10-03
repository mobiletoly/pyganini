"""Application-owned policy on a declaration-free static section."""

from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PrivacyPolicy:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def tagged(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-content-section", b"privacy"),
                    ],
                }
            await send(message)

        await self.app(scope, receive, tagged)


MIDDLEWARE = (Middleware(PrivacyPolicy),)
