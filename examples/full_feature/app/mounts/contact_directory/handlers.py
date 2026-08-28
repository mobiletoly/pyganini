"""Handlers for the reusable contact-directory route source."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from pyganini import (
    FragmentResponse,
    FragmentRouteResponse,
    Page,
    PageMetadata,
    RouteResponse,
    csrf,
    hx,
    nav,
)
from pyganini.request_data import Form, Upload
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.contacts import Contact
from app.dependencies import from_request


@dataclass(frozen=True, slots=True)
class ContactDirectoryURLs:
    """Owner-generated URLs supplied to the reusable source."""

    home_url: str
    page_url: str
    table_url: str
    create_url: str | None
    detail_url: Callable[[str], str] | None


@dataclass(frozen=True, slots=True)
class ContactDirectoryKit:
    """Request-scoped owner state for the reusable contact directory."""

    urls: ContactDirectoryURLs
    contacts: tuple[Contact, ...]
    layout: Mapping[str, object]
    title: str
    description: str
    show_create: bool


@dataclass(frozen=True, slots=True)
class ContactForm:
    """Contact form values and validation messages."""

    name: str = ""
    status: str = "Active"
    name_error: str = ""
    status_error: str = ""

    @property
    def has_errors(self) -> bool:
        """Return whether either visible field has a validation error."""
        return bool(self.name_error or self.status_error)


def _filter_urls(directory: ContactDirectoryKit) -> dict[str, str]:
    """Build filter query strings from the owner-provided table URL."""
    table_path = directory.urls.table_url
    return {
        "all": table_path,
        "active": f"{table_path}?{urlencode({'status': 'active'})}",
        "inactive": f"{table_path}?{urlencode({'status': 'inactive'})}",
    }


def _directory_context(
    request: Request,
    directory: ContactDirectoryKit,
    form: ContactForm,
    contacts: tuple[Contact, ...],
    upload_filename: str = "",
    *,
    inspect_table_fragment: bool = False,
) -> dict[str, object]:
    """Build explicit context for the page, fragment, and action."""
    return {
        "directory": directory,
        "form": form,
        "contacts": contacts,
        "upload_filename": upload_filename,
        "csrf_token": csrf.token(request),
        "filter_urls": _filter_urls(directory),
        "navigation": nav(request).navigation(),
        "inspect_table_fragment": inspect_table_fragment,
    }


def _metadata(directory: ContactDirectoryKit) -> PageMetadata:
    return PageMetadata(title=directory.title, description=directory.description)


async def page(directory: ContactDirectoryKit, request: Request) -> Page:
    """Render the source page for one live owner."""
    if request.headers.get("X-Example-Route-Error") == "matched":
        raise HTTPException(status_code=418)
    return Page(
        context=_directory_context(
            request,
            directory,
            ContactForm(),
            directory.contacts,
            inspect_table_fragment=True,
        ),
        metadata=_metadata(directory),
        layout=directory.layout,
    )


def _filter_status(request: Request) -> str | None:
    selected = request.query_params.get("status", "")
    return {"active": "Active", "inactive": "Inactive"}.get(selected)


async def table(
    directory: ContactDirectoryKit, request: Request
) -> FragmentRouteResponse:
    """Render the standalone table fragment without layouts."""
    selected_status = _filter_status(request)
    return FragmentResponse(
        context={
            "directory": directory,
            "contacts": tuple(
                contact
                for contact in directory.contacts
                if selected_status is None or contact.status == selected_status
            ),
        }
    )


def _first_value(form: Form, name: str) -> object:
    values = form.values(name)
    return values[0] if values else ""


def post_create(
    directory: ContactDirectoryKit, request: Request, form: Form
) -> RouteResponse:
    """Validate and create one contact through HTMX or ordinary HTML."""
    dependencies = from_request(request)
    csrf_value: object
    name_value: object
    status_value: object
    upload_filename = ""
    csrf_values = tuple(
        value for field, value in form.items if field == csrf.FIELD_NAME
    )
    if len(csrf_values) != 1 or not isinstance(csrf_values[0], str):
        return Response("Forbidden", status_code=403)
    csrf_value = csrf_values[0]
    try:
        dependencies.csrf.validate(request, csrf_value)
    except csrf.ValidationError:
        return Response("Forbidden", status_code=403)

    name_value = _first_value(form, "name")
    status_value = _first_value(form, "status")
    avatar_values = tuple(value for field, value in form.items if field == "avatar")
    if len(avatar_values) > 1 or any(
        not isinstance(value, Upload) for value in avatar_values
    ):
        return Response("Invalid avatar upload", status_code=413)
    upload = avatar_values[0] if avatar_values else None
    if isinstance(upload, Upload):
        upload_filename = upload.filename or ""

    name = name_value if isinstance(name_value, str) else ""
    status = status_value if isinstance(status_value, str) else ""
    form_value = ContactForm(
        name=name,
        status=status,
        name_error=(
            "Name is required."
            if not isinstance(name_value, str) or not name.strip()
            else ""
        ),
        status_error=(
            "Choose a valid status."
            if not isinstance(status_value, str) or status not in {"Active", "Inactive"}
            else ""
        ),
    )
    if form_value.has_errors:
        contacts = directory.contacts
        if hx.is_request(request):
            return FragmentResponse(
                context=_directory_context(request, directory, form_value, contacts),
                status_code=422,
                headers={
                    hx.HEADER_RETARGET: "#users-directory",
                    hx.HEADER_RESWAP: "outerHTML",
                },
            )
        return Page(
            context=_directory_context(request, directory, form_value, contacts),
            metadata=_metadata(directory),
            layout=directory.layout,
            status_code=422,
        )

    dependencies.repository.add_contact(name.strip(), status, upload_filename)
    if hx.is_request(request):
        return FragmentResponse(
            context=_directory_context(
                request,
                directory,
                ContactForm(),
                dependencies.repository.list_contacts(),
                upload_filename,
            ),
            headers={
                hx.HEADER_RETARGET: "#users-directory",
                hx.HEADER_RESWAP: "outerHTML",
                hx.HEADER_TRIGGER: "contact:created",
            },
        )
    return RedirectResponse(directory.urls.page_url, status_code=303)
