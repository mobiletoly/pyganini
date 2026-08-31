from pyganini import action, route
from pyganini.request_data import capture_form

from .handlers import page, post_join

Route = route(
    page=page,
    template="page.jinja",
    actions=(
        action(
            "POST",
            "/join",
            post_join,
            template="join_form.jinja",
            request_data=capture_form(
                max_files=1,
                max_fields=4,
                max_part_size=4096,
                max_upload_size=4096,
            ),
        ),
    ),
)
