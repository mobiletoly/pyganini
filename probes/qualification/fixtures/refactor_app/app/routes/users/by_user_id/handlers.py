from __future__ import annotations

from pyganini import Page, PageMetadata
from starlette.requests import Request


def page(request: Request) -> Page:
    user_id = request.path_params["user_id"]
    return Page(
        context={"user_id": user_id},
        metadata=PageMetadata(title=f"User {user_id}"),
        layout={"section": "users"},
    )
