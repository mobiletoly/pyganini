"""Explicit page frame and record resolution helpers."""

from __future__ import annotations

from collections.abc import Mapping

from pyganini import Navigation, Page, PageMetadata
from starlette.requests import Request
from starlette.responses import Response

from app._pyganini.urls import urls
from app.store import STORE, Customer, Office, Team
from assets import pyganini_assets_gen as assets


def root_path(request: Request) -> str:
    value = request.scope.get("root_path", "")
    return value if isinstance(value, str) else ""


def layout(request: Request, navigation: Navigation) -> dict[str, object]:
    base_path = root_path(request)
    return {
        "navigation": navigation,
        "stylesheet_url": assets.path("app.css", base_path=base_path),
        "urls": urls.with_base_path(base_path),
    }


def page_response(
    request: Request,
    navigation: Navigation,
    context: Mapping[str, object],
    *,
    title: str,
    description: str,
) -> Page:
    return Page(
        context=dict(context),
        metadata=PageMetadata(title=title, description=description),
        layout=layout(request, navigation),
    )


def not_found(kind: str) -> Response:
    return Response(f"{kind} not found", status_code=404)


def hq_team(request: Request) -> Team | None:
    team = STORE.team(request.path_params.get("team_id", ""))
    return team if team is not None and team.office_identifier is None else None


def regional_office(request: Request) -> Office | None:
    return STORE.office(request.path_params.get("office_id", ""))


def regional_team(request: Request, office: Office) -> Team | None:
    team = STORE.team(request.path_params.get("team_id", ""))
    if team is None or team.office_identifier != office.identifier:
        return None
    return team


def owned_customer(request: Request, team: Team) -> Customer | None:
    customer = STORE.customer(request.path_params.get("customer_id", ""))
    if customer is None or customer.team_identifier != team.identifier:
        return None
    return customer
