"""Root page and join action handlers."""

from __future__ import annotations

from dataclasses import dataclass

from pyganini import FragmentResponse, Page, PageMetadata, RouteResponse
from pyganini.request_data import Form
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app._pyganini.urls import urls
from app.presentation import layout, root_path
from app.session import MAX_NAME_LENGTH, set_name


@dataclass(frozen=True, slots=True)
class JoinForm:
    name: str = ""
    name_error: str = ""


def _single_text(form: Form, field: str) -> str:
    values = form.values(field)
    return values[0] if len(values) == 1 else ""


def page(request: Request) -> Page:
    app_urls = urls.with_base_path(root_path(request))
    return Page(
        context={"form": JoinForm(), "join_url": app_urls.join.path},
        metadata=PageMetadata(
            title="Join Chat - Pyganini Chat",
            description="Choose a display name for the Pyganini SSE chat example.",
        ),
        layout=layout(request),
    )


def post_join(request: Request, form: Form) -> RouteResponse:
    raw_name = _single_text(form, "name")
    name = raw_name.strip()
    error = ""
    if not name:
        error = "Enter your name."
    elif len(name) > MAX_NAME_LENGTH:
        error = f"Use {MAX_NAME_LENGTH} characters or fewer."
    if error:
        app_urls = urls.with_base_path(root_path(request))
        return FragmentResponse(
            context={
                "form": JoinForm(name=raw_name, name_error=error),
                "join_url": app_urls.join.path,
            },
            status_code=422,
        )

    app_urls = urls.with_base_path(root_path(request))
    response = RedirectResponse(app_urls.chat.path, status_code=303)
    set_name(response, name)
    return response
