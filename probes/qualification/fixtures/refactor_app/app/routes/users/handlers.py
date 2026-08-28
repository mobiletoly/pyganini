from __future__ import annotations

from pyganini import FragmentResponse, Page, PageMetadata
from starlette.requests import Request
from starlette.responses import PlainTextResponse


def page(_: Request) -> Page:
    return Page(
        context={"users": ("Ada", "Grace")},
        metadata=PageMetadata(title="Users"),
        layout={"section": "users"},
    )


def table(_: Request) -> FragmentResponse:
    return FragmentResponse(context={"users": ("Ada", "Grace")})


def save(_: Request) -> PlainTextResponse:
    return PlainTextResponse("saved", status_code=201)
