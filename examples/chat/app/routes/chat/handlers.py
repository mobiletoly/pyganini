"""Chat page and action handlers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pyganini import FragmentResponse, Page, PageMetadata, RouteResponse
from pyganini.request_data import Form
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app._pyganini.urls import urls
from app.events import EVENTS_PATH
from app.presentation import layout, root_path
from app.runtime import room, send_delay
from app.session import clear_name, usable_name

MAX_MESSAGE_LENGTH = 2_000


@dataclass(frozen=True, slots=True)
class MessageForm:
    body: str = ""
    body_error: str = ""


def _single_text(form: Form, field: str) -> str:
    values = form.values(field)
    return values[0] if len(values) == 1 else ""


def _events_url(request: Request, after_id: int) -> str:
    app_urls = urls.with_base_path(root_path(request))
    external_base = app_urls.root.path.removesuffix("/")
    path = f"{external_base}{EVENTS_PATH}"
    return f"{path}?after={after_id}" if after_id > 0 else path


async def page(request: Request) -> Page:
    name = usable_name(request)
    messages = await room(request).messages()
    app_urls = urls.with_base_path(root_path(request))
    last_id = messages[-1].identifier if messages else 0
    return Page(
        context={
            "name": name,
            "messages": messages,
            "form": MessageForm(),
            "root_url": app_urls.root.path,
            "message_url": app_urls.chat.message.path,
            "sign_out_url": app_urls.chat.sign_out.path,
            "events_url": _events_url(request, last_id),
        },
        metadata=PageMetadata(
            title="Chat - Pyganini Chat",
            description="A process-local Server-Sent Event chat example.",
        ),
        layout=layout(request),
    )


async def post_message(request: Request, form: Form) -> RouteResponse:
    name = usable_name(request)
    if not name:
        return Response("Join the chat first", status_code=401)

    raw_body = _single_text(form, "body")
    body = raw_body.strip()
    error = ""
    if not body:
        error = "Enter a message."
    elif len(body) > MAX_MESSAGE_LENGTH:
        error = f"Use {MAX_MESSAGE_LENGTH} characters or fewer."
    if error:
        app_urls = urls.with_base_path(root_path(request))
        return FragmentResponse(
            context={
                "form": MessageForm(body=raw_body, body_error=error),
                "message_url": app_urls.chat.message.path,
            },
            status_code=422,
        )

    await asyncio.sleep(send_delay(request))
    await room(request).publish(name, body)
    app_urls = urls.with_base_path(root_path(request))
    return FragmentResponse(
        context={
            "form": MessageForm(),
            "message_url": app_urls.chat.message.path,
        }
    )


def post_sign_out(request: Request) -> RedirectResponse:
    app_urls = urls.with_base_path(root_path(request))
    response = RedirectResponse(app_urls.root.path, status_code=303)
    clear_name(response)
    return response
