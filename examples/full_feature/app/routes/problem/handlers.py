"""Handlers for the application-owned error presentation demonstration."""

from __future__ import annotations

from starlette.requests import Request


def page(_: Request) -> None:
    """Raise a real generated-route failure for the app-owned callback."""
    raise RuntimeError("full-feature route failure")
