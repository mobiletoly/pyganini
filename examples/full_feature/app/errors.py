"""Application-owned generated-route error presentation."""

from __future__ import annotations

from pyganini import FragmentResponse, Page, PageMetadata, RouteErrorHandler
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.routes.handlers import build_layout


def present_route_error(
    request: Request, error: Exception
) -> Page | FragmentResponse | PlainTextResponse | None:
    """Select one application-owned generated-route error presentation."""
    status_code = error.status_code if isinstance(error, HTTPException) else 500
    title = {
        404: "Page not found",
        405: "Method not allowed",
        413: "Request is too large",
        415: "Unsupported media type",
        418: "Matched route failed",
    }.get(status_code, "Request failed")
    presentation = request.headers.get("X-Error-Presentation")
    if presentation == "direct":
        return PlainTextResponse("Direct application error", status_code=status_code)
    if presentation == "delegate":
        return None
    if request.headers.get("HX-Request") == "true":
        return FragmentResponse(
            context={"status_code": status_code, "title": title},
            status_code=status_code,
            headers={
                "HX-Retarget": "#global-error",
                "HX-Reswap": "outerHTML",
            },
        )
    return Page(
        context={"status_code": status_code, "title": title},
        metadata=PageMetadata(
            title=f"{title} - Pyganini Contact Directory",
            description="Application-owned generated-route error presentation.",
        ),
        layout=build_layout(request, ""),
        status_code=status_code,
    )


route_error_handler: RouteErrorHandler = present_route_error
