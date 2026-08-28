"""Handlers for dynamic contact detail pages in the source tree."""

from __future__ import annotations

from pyganini import Page, PageMetadata, current_nav_step, nav, nav_step
from starlette.requests import Request
from starlette.responses import Response

from app.dependencies import from_request

from ..handlers import ContactDirectoryKit


async def page(directory: ContactDirectoryKit, request: Request) -> Page | Response:
    """Render one contact or return a direct 404 response."""
    dependencies = from_request(request)
    identifier = request.path_params["id"]
    contact = dependencies.repository.contact_by_id(identifier)
    if contact is None:
        return Response("Contact not found", status_code=404)
    request_navigation = nav(request)
    request_navigation.resolve("contact", contact.name)
    navigation = request_navigation.navigation()
    if request_navigation.trail_key() == "from-contacts":
        navigation = request_navigation.navigation_with_trail(
            (
                nav_step("Home", directory.urls.home_url),
                nav_step("Contacts", directory.urls.page_url),
                current_nav_step(contact.name),
            )
        )
    return Page(
        context={
            "contact": contact,
            "directory": directory,
            "navigation": navigation,
        },
        metadata=PageMetadata(
            title=f"{contact.name} - Pyganini Contact Directory",
            description=f"Details for contact {contact.name}.",
        ),
        layout=directory.layout,
    )
