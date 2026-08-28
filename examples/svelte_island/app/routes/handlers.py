"""Root page and Save handlers."""

from __future__ import annotations

import json
from typing import cast

from pyganini import Page, PageMetadata, csrf
from pyganini.request_data import Body
from starlette.requests import Request
from starlette.responses import JSONResponse

from app._pyganini.urls import urls
from app.state import Project, from_request
from assets import pyganini_assets_gen as assets

NO_STORE = {"Cache-Control": "no-store"}


def root_path(request: Request) -> str:
    value = request.scope.get("root_path", "")
    return value if isinstance(value, str) else ""


def build_layout(request: Request) -> dict[str, object]:
    """Build the explicit application-owned root layout mapping."""
    base_path = root_path(request)
    app_urls = urls.with_base_path(base_path)
    return {
        "framework": "Svelte",
        "root_url": app_urls.root.path,
        "about_url": app_urls.about.path,
        "csrf_meta_name": csrf.META_NAME,
        "csrf_token": csrf.token(request),
        "stylesheet_url": assets.path("app.css", base_path=base_path),
        "htmx_script_url": assets.path("vendor/htmx.min.js", base_path=base_path),
        "app_script_url": assets.path("app.js", base_path=base_path),
    }


def page(request: Request) -> Page:
    """Render the server-owned page around one empty client island."""
    app_urls = urls.with_base_path(root_path(request))
    project = from_request(request).store.read()
    return Page(
        context={
            "framework": "Svelte",
            "project_name": project.name,
            "project_pinned": project.pinned,
            "save_url": app_urls.save.path,
            "cancel_url": app_urls.about.path,
        },
        metadata=PageMetadata(
            title="Svelte island - Pyganini",
            description="A bounded application-owned Svelte client island.",
        ),
        layout=build_layout(request),
    )


def _json(payload: object, status_code: int) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, headers=NO_STORE)


def save(request: Request, body: Body) -> JSONResponse:
    """Validate and persist one bounded JSON project update."""
    dependencies = from_request(request)
    token = request.headers.get(csrf.HEADER_NAME, "")
    try:
        dependencies.csrf.validate(request, token)
    except csrf.ValidationError:
        return _json({"error": "forbidden"}, 403)

    media_type = request.headers.get("content-type", "").split(";", 1)[0]
    if media_type.strip().lower() != "application/json":
        return _json({"error": "unsupported media type"}, 415)

    try:
        value: object = json.loads(body.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json({"error": "bad request"}, 400)

    if not isinstance(value, dict):
        return _json({"error": "bad request"}, 400)

    payload = cast(dict[object, object], value)
    if len(payload) != 2 or "name" not in payload or "pinned" not in payload:
        return _json({"error": "bad request"}, 400)

    name_value = payload["name"]
    pinned_value = payload["pinned"]
    if not isinstance(name_value, str) or not isinstance(pinned_value, bool):
        return _json({"error": "bad request"}, 400)
    name = name_value.strip()
    if not name:
        return _json({"errors": {"name": "Enter a project name."}}, 422)

    project = dependencies.store.save(Project(name=name, pinned=pinned_value))
    return _json(
        {"project": {"name": project.name, "pinned": project.pinned}},
        200,
    )
