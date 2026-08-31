from pyganini import action, route
from pyganini.request_data import capture_form

from .handlers import page, post_message, post_sign_out

Route = route(
    page=page,
    template="page.jinja",
    actions=(
        action(
            "POST",
            "/message",
            post_message,
            template="composer.jinja",
            request_data=capture_form(
                max_files=1,
                max_fields=4,
                max_part_size=65_536,
                max_upload_size=65_536,
            ),
        ),
        action("POST", "/sign-out", post_sign_out),
    ),
)
