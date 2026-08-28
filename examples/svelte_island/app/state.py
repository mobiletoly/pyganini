"""Application-owned project state and dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from pyganini import csrf
from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class Project:
    """One immutable project value."""

    name: str
    pinned: bool


class ProjectStore:
    """Keep the example project behind a small thread-safe boundary."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._project = Project(name="Pyganini island", pinned=False)

    def read(self) -> Project:
        """Return the current immutable project."""
        with self._lock:
            return self._project

    def save(self, project: Project) -> Project:
        """Replace and return the current project."""
        with self._lock:
            self._project = project
            return self._project


@dataclass(frozen=True, slots=True)
class Dependencies:
    """Application dependencies visible to request handlers."""

    store: ProjectStore
    csrf: csrf.Guard


def from_request(request: Request) -> Dependencies:
    """Read typed application dependencies from Starlette state."""
    value = getattr(request.app.state, "dependencies", None)
    if not isinstance(value, Dependencies):
        raise RuntimeError("application dependency state is missing or invalid")
    return value
