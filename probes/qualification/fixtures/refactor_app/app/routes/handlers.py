from __future__ import annotations

from pyganini import Page, PageMetadata
from starlette.requests import Request

from app._pyganini.urls import urls


def page(_: Request) -> Page:
    return Page(
        context={"message": "qualification home", "users_url": urls.users.path},
        metadata=PageMetadata(title="Qualification"),
        layout={"section": "home"},
    )
