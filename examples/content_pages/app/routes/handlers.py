"""Request work finishes before rendering."""

from pyganini import Page, PageMetadata
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.shell import layout


def page(request: Request) -> Page:
    return Page(metadata=PageMetadata("Pyganini Content Pages"), layout=layout(request))


def declared(request: Request) -> PlainTextResponse:
    return PlainTextResponse("Declared routes take precedence.")
