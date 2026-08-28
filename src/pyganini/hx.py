"""Small typed helpers for HTMX request and response headers."""

from __future__ import annotations

from starlette.requests import Request

HEADER_BOOSTED: str = "HX-Boosted"
HEADER_CURRENT_URL: str = "HX-Current-URL"
HEADER_HISTORY_RESTORE_REQUEST: str = "HX-History-Restore-Request"
HEADER_PROMPT: str = "HX-Prompt"
HEADER_REQUEST: str = "HX-Request"
HEADER_TARGET: str = "HX-Target"
HEADER_TRIGGER: str = "HX-Trigger"
HEADER_TRIGGER_NAME: str = "HX-Trigger-Name"

HEADER_LOCATION: str = "HX-Location"
HEADER_PUSH_URL: str = "HX-Push-Url"
HEADER_REDIRECT: str = "HX-Redirect"
HEADER_REFRESH: str = "HX-Refresh"
HEADER_REPLACE_URL: str = "HX-Replace-Url"
HEADER_RESELECT: str = "HX-Reselect"
HEADER_RETARGET: str = "HX-Retarget"
HEADER_RESWAP: str = "HX-Reswap"
HEADER_TRIGGER_AFTER_SETTLE: str = "HX-Trigger-After-Settle"
HEADER_TRIGGER_AFTER_SWAP: str = "HX-Trigger-After-Swap"

__all__ = [
    "HEADER_BOOSTED",
    "HEADER_CURRENT_URL",
    "HEADER_HISTORY_RESTORE_REQUEST",
    "HEADER_LOCATION",
    "HEADER_PROMPT",
    "HEADER_PUSH_URL",
    "HEADER_REDIRECT",
    "HEADER_REFRESH",
    "HEADER_REPLACE_URL",
    "HEADER_REQUEST",
    "HEADER_RESELECT",
    "HEADER_RESWAP",
    "HEADER_RETARGET",
    "HEADER_TARGET",
    "HEADER_TRIGGER",
    "HEADER_TRIGGER_AFTER_SETTLE",
    "HEADER_TRIGGER_AFTER_SWAP",
    "HEADER_TRIGGER_NAME",
    "current_url",
    "is_boosted",
    "is_history_restore_request",
    "is_request",
    "prompt",
    "target",
    "trigger_id",
    "trigger_name",
]


def _is_true(request: Request, header: str) -> bool:
    return request.headers.get(header, "") == "true"


def is_request(request: Request) -> bool:
    """Return whether the request was made by HTMX."""
    return _is_true(request, HEADER_REQUEST)


def is_boosted(request: Request) -> bool:
    """Return whether HTMX boosted the request."""
    return _is_true(request, HEADER_BOOSTED)


def is_history_restore_request(request: Request) -> bool:
    """Return whether HTMX is restoring browser history."""
    return _is_true(request, HEADER_HISTORY_RESTORE_REQUEST)


def current_url(request: Request) -> str:
    """Return HTMX's current browser URL request header."""
    return request.headers.get(HEADER_CURRENT_URL, "")


def prompt(request: Request) -> str:
    """Return HTMX's prompt response from the request header."""
    return request.headers.get(HEADER_PROMPT, "")


def target(request: Request) -> str:
    """Return the HTMX target element identifier from the request."""
    return request.headers.get(HEADER_TARGET, "")


def trigger_id(request: Request) -> str:
    """Return the HTMX triggering element identifier from the request."""
    return request.headers.get(HEADER_TRIGGER, "")


def trigger_name(request: Request) -> str:
    """Return the HTMX triggering element name from the request."""
    return request.headers.get(HEADER_TRIGGER_NAME, "")
