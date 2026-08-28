"""Handlers for the root route."""

from __future__ import annotations

from pyganini import Page, PageMetadata, TemplateInspectionMode, browser, csrf, nav
from starlette.requests import Request

from app._pyganini.urls import urls
from assets import pyganini_assets_gen as assets


def _root_path(request: Request) -> str:
    value = request.scope.get("root_path", "")
    return value if isinstance(value, str) else ""


def build_layout(request: Request, active_nav: str) -> dict[str, object]:
    """Build the explicit root layout mapping."""
    root_path = _root_path(request)
    app_urls = urls.with_base_path(root_path)
    external_base_path = app_urls.root.path.removesuffix("/")
    template_inspection = getattr(
        request.app.state,
        "template_inspection",
        TemplateInspectionMode.OFF,
    )
    route_policy = getattr(request.state, "route_policy", "host")
    if not isinstance(route_policy, str):
        route_policy = "host"
    return {
        "urls": app_urls,
        "active_nav": active_nav,
        "csrf_token": csrf.token(request),
        "route_policy": route_policy,
        "stylesheet_url": assets.path("app.css", base_path=root_path),
        "htmx_script_url": assets.path("vendor/htmx.min.js", base_path=root_path),
        "sse_extension_script_url": assets.path(
            "vendor/hx-sse.min.js", base_path=root_path
        ),
        "sse_helper_script_url": (
            f"{external_base_path}/pyganini{browser.SSE_EVENT_HELPER_PATH}"
        ),
        "template_inspector_script_url": (
            f"{external_base_path}/pyganini{browser.TEMPLATE_INSPECTOR_HELPER_PATH}"
            if template_inspection is TemplateInspectionMode.OVERLAY
            else None
        ),
        "app_script_url": assets.path("app.js", base_path=root_path),
    }


def page(request: Request) -> Page:
    """Render the product introduction page."""
    app_urls = urls.with_base_path(_root_path(request))
    external_base_path = app_urls.root.path.removesuffix("/")
    navigation = nav(request).navigation()
    return Page(
        context={
            "urls": app_urls,
            "navigation": navigation,
            "events_url": f"{external_base_path}/events",
        },
        metadata=PageMetadata(
            title="Pyganini Contact Directory",
            description="A server-rendered contact directory built with Pyganini.",
        ),
        layout=build_layout(request, "home"),
    )
