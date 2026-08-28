"""Select an application root and validate its fixed package boundaries."""

from dataclasses import dataclass
from pathlib import Path

from pyganini._config import ConfigError, has_pyganini_marker


class PathError(ValueError):
    """A localized root-selection or project-layout failure."""

    def __init__(self, code: str, phase: str, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.phase = phase
        self.path = path
        self.message = message


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    app: Path
    routes: Path
    mounts: Path | None
    generated: Path


def _resolve_directory(path: Path, role: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PathError(
            "PYGANINI002",
            "root-selection",
            str(path),
            f"{role} cannot be resolved: {error}",
        ) from error
    if not resolved.is_dir():
        raise PathError(
            "PYGANINI002",
            "root-selection",
            str(path),
            f"{role} must be an existing directory",
        )
    return resolved


def _marker_at(root: Path, *, required: bool) -> bool:
    marker = root / "pyproject.toml"
    if not marker.is_file():
        if required:
            raise ConfigError(marker, "missing pyproject.toml with [tool.pyganini]")
        return False
    return has_pyganini_marker(marker, required=required)


def _select_root(*, explicit: Path | None, start: Path | None) -> Path:
    if explicit is not None:
        root = _resolve_directory(explicit, "explicit root")
        _marker_at(root, required=True)
        return root

    physical_start = _resolve_directory(
        Path.cwd() if start is None else start, "working directory"
    )
    boundary = Path(physical_start.anchor)
    current = physical_start
    while True:
        if _marker_at(current, required=False):
            return current
        if current == boundary:
            break
        current = current.parent
    raise PathError(
        "PYGANINI001",
        "root-selection",
        "pyganini",
        (
            f"no [tool.pyganini] marker found from {physical_start} "
            f"through boundary {boundary}"
        ),
    )


def _layout_error(path: Path, message: str) -> PathError:
    return PathError("PYGANINI004", "project-layout", path.as_posix(), message)


def _validate_boundary(*, root: Path, path: Path, kind: str, relative: str) -> None:
    if path.is_symlink():
        raise _layout_error(Path(relative), f"required {kind} must not be a symlink")
    valid = path.is_dir() if kind == "directory" else path.is_file()
    if not valid:
        raise _layout_error(Path(relative), f"required {kind} is missing or invalid")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise _layout_error(
            Path(relative), f"required {kind} cannot resolve: {error}"
        ) from error
    if not resolved.is_relative_to(root):
        raise _layout_error(
            Path(relative), f"required {kind} escapes the application root"
        )


def select_project_paths(
    *,
    explicit: Path | None,
    start: Path | None = None,
    validate_generated: bool = True,
) -> ProjectPaths:
    """Select and validate the fixed application package paths.

    ``validate_generated=False`` is reserved for source-only inspection. It
    validates application-owned source boundaries and does not inspect the
    generated root. The default preserves generation and check behavior.
    """
    root = _select_root(explicit=explicit, start=start)
    app = root / "app"
    routes = app / "routes"
    mounts_path = app / "mounts"
    generated = app / "_pyganini"

    _validate_boundary(root=root, path=app, kind="directory", relative="app")
    _validate_boundary(
        root=root,
        path=app / "__init__.py",
        kind="regular file",
        relative="app/__init__.py",
    )
    _validate_boundary(root=root, path=routes, kind="directory", relative="app/routes")
    _validate_boundary(
        root=root,
        path=routes / "__init__.py",
        kind="regular file",
        relative="app/routes/__init__.py",
    )

    mounts: Path | None
    if mounts_path.exists() or mounts_path.is_symlink():
        _validate_boundary(
            root=root, path=mounts_path, kind="directory", relative="app/mounts"
        )
        mounts = mounts_path
    else:
        mounts = None

    if validate_generated:
        if generated.is_symlink():
            raise _layout_error(
                Path("app/_pyganini"), "generated directory must not be a symlink"
            )
        if generated.exists() and not generated.is_dir():
            raise _layout_error(
                Path("app/_pyganini"), "generated path must be a directory when present"
            )
    return ProjectPaths(
        root=root,
        app=app,
        routes=routes,
        mounts=mounts,
        generated=generated,
    )
