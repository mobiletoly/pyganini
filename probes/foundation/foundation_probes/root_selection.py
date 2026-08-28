from collections.abc import Sequence
from pathlib import Path

PROBE_MARKER = ".pyganini-probe-root"


class RootSelectionError(ValueError):
    pass


def _resolve(path: Path, role: str) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise RootSelectionError(
            f"root-selection phase: {role} {path} cannot be resolved: {error}"
        ) from error


def _markers_at(path: Path, marker_names: Sequence[str]) -> tuple[str, ...]:
    return tuple(name for name in marker_names if (path / name).is_file())


def _validated_candidate(path: Path, marker_names: Sequence[str]) -> Path:
    found = _markers_at(path, marker_names)
    if not found:
        raise RootSelectionError(
            f"root-selection phase: no project marker at explicit root {path}"
        )
    if len(found) > 1:
        raise RootSelectionError(
            f"root-selection phase: ambiguous markers at {path}: {', '.join(found)}"
        )
    return path


def select_root(
    *,
    explicit: Path | None,
    start: Path,
    boundary: Path,
    marker_names: Sequence[str] = (PROBE_MARKER,),
) -> Path:
    """Select an explicit root or search upward within a physical boundary."""
    if explicit is not None:
        return _validated_candidate(_resolve(explicit, "explicit root"), marker_names)

    physical_boundary = _resolve(boundary, "boundary")
    physical_start = _resolve(start, "start")
    current = physical_start
    if current.is_file():
        current = current.parent
    if not current.is_relative_to(physical_boundary):
        raise RootSelectionError(
            f"root-selection phase: start {current} is outside boundary "
            f"{physical_boundary}"
        )
    while True:
        found = _markers_at(current, marker_names)
        if len(found) > 1:
            raise RootSelectionError(
                f"root-selection phase: ambiguous markers at {current}: "
                f"{', '.join(found)}"
            )
        if found:
            return current
        if current == physical_boundary:
            break
        current = current.parent
    raise RootSelectionError(
        f"root-selection phase: no project marker from {physical_start} "
        f"through boundary {physical_boundary}"
    )
