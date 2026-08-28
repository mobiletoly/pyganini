from pyganini import RouteNav, mount_route, nav, route_mount, to
from starlette.requests import Request

from app._pyganini.urls import mount_urls, urls
from app.dependencies import from_request
from app.mounts.contact_directory.handlers import (
    ContactDirectoryKit,
    ContactDirectoryURLs,
)
from app.routes.handlers import build_layout


def create_users(request: Request) -> ContactDirectoryKit:
    """Bind the selected contact-directory source to the users owner."""
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    owner_urls = mount_urls.contact_directory.bind(app_urls.users)
    navigation = nav(request).navigation()
    return ContactDirectoryKit(
        urls=ContactDirectoryURLs(
            home_url=app_urls.root.path,
            page_url=owner_urls.path,
            table_url=owner_urls.table.path,
            create_url=owner_urls.create.path,
            detail_url=lambda identifier: app_urls.users.destinations.contact_detail(
                identifier
            ).navigation_href(navigation),
        ),
        contacts=from_request(request).repository.list_contacts(),
        layout=build_layout(request, "users"),
        title="Contacts - Pyganini Contact Directory",
        description="Browse and create contacts in the in-memory directory.",
        show_create=True,
    )


Route = route_mount(
    create=create_users,
    mount="contact_directory",
    routes=(
        mount_route(
            "/",
            nav=RouteNav(label="Contacts"),
            destinations=(
                to(
                    "contact-detail",
                    urls.users.by_id,
                    trail_key="from-contacts",
                ),
            ),
        ),
        mount_route("/create"),
        mount_route("/{id}"),
    ),
)
