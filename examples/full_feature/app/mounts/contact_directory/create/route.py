from pyganini import kit_action, route_kit
from pyganini.request_data import capture_form

from .handlers import post_create

Route = route_kit(
    actions=(
        kit_action(
            "POST",
            "/",
            post_create,
            request_data=capture_form(
                max_files=4,
                max_fields=16,
                max_part_size=65_536,
                max_upload_size=65_536,
            ),
            template="directory.jinja",
        ),
    ),
)
