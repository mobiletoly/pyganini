"""Root page and bounded Save action declaration."""

from pyganini import action, route
from pyganini.request_data import capture_body

from .handlers import page, save

Route = route(
    page=page,
    template="page.jinja",
    actions=(
        action(
            "POST",
            "/save",
            save,
            request_data=capture_body(max_bytes=4096),
        ),
    ),
)
