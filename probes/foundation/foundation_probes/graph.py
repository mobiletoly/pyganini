from dataclasses import dataclass
from typing import Final, Literal


@dataclass(frozen=True, slots=True)
class GraphRoute:
    name: str
    path: str
    endpoint: Literal["home", "user"]
    parameters: tuple[tuple[str, type[int]], ...] = ()
    children: tuple[tuple[str, str], ...] = ()


SYNTHETIC_GRAPH: Final[tuple[GraphRoute, ...]] = (
    GraphRoute(name="home", path="/", endpoint="home"),
    GraphRoute(
        name="user",
        path="/users/{user_id:int}",
        endpoint="user",
        parameters=(("user_id", int),),
        children=(("edit", "edit"),),
    ),
)
