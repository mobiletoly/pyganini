"""Explicit application layout data."""

from starlette.requests import Request

from app._pyganini.urls import urls
from assets import pyganini_assets_gen as assets


def layout(request: Request) -> dict[str, object]:
    raw = request.scope.get("root_path", "")
    base = raw if isinstance(raw, str) else ""
    bound = urls.with_base_path(base)
    return {
        "urls": bound,
        "base": bound.root.path.removesuffix("/"),
        "dev_reload_script_url": (
            assets.path("dev-reload.js", base_path=base)
            if getattr(request.app.state, "dev_reload_enabled", False)
            else None
        ),
        "dev_reload_events_url": f"{bound.root.path.removesuffix('/')}/_example/reload",
        "stylesheet_url": assets.path("app.css", base_path=base),
    }
