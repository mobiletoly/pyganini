import fragments as fragment_handlers
from actions import save as imported_save
from fragments import details
from probe_syntax import route


def local_page() -> None:
    pass


ROUTE = route(
    path="/users/{user_id}",
    parameters=("user_id",),
    page=local_page,
    fragments=(fragment_handlers.summary, details),
    actions=(imported_save,),
    metadata={"section": "users", "title": "User"},
)

raise RuntimeError("static discovery imported the fixture")
