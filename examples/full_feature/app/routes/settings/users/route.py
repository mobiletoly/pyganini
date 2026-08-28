from pyganini import mount_route, route_mount
from starlette.requests import Request

from app._pyganini.urls import mount_urls, urls
from app.dependencies import from_request
from app.mounts.contact_directory.handlers import (
    ContactDirectoryKit,
    ContactDirectoryURLs,
)
from app.routes.handlers import build_layout


def create_settings_users(request: Request) -> ContactDirectoryKit:
    """Bind only the source root to the settings owner."""
    app_urls = urls.with_base_path(request.scope.get("root_path", ""))
    owner_urls = mount_urls.contact_directory.bind(app_urls.settings.users)
    return ContactDirectoryKit(
        urls=ContactDirectoryURLs(
            home_url=app_urls.root.path,
            page_url=owner_urls.path,
            table_url=owner_urls.table.path,
            create_url=None,
            detail_url=None,
        ),
        contacts=from_request(request).repository.list_contacts("Active"),
        layout=build_layout(request, "settings"),
        title="Settings Contacts - Pyganini Contact Directory",
        description="Read-only contact directory supplied by the settings owner.",
        show_create=False,
    )


Route = route_mount(
    create=create_settings_users,
    mount="contact_directory",
    routes=(mount_route("/"),),
)
