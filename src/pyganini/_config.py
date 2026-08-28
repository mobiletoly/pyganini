"""Load the single application marker from ``pyproject.toml``."""

import tomllib
from pathlib import Path
from typing import cast


class ConfigError(ValueError):
    """A localized configuration failure."""

    code = "PYGANINI003"
    phase = "configuration"

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def has_pyganini_marker(path: Path, *, required: bool) -> bool:
    """Return whether *path* contains the valid, empty Pyganini marker."""
    try:
        with path.open("rb") as source:
            document = cast(dict[str, object], tomllib.load(source))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(path, f"malformed TOML: {error}") from error
    except OSError as error:
        raise ConfigError(
            path, f"cannot read project configuration: {error}"
        ) from error

    tool = document.get("tool")
    if tool is None:
        if required:
            raise ConfigError(path, "missing [tool.pyganini] table")
        return False
    if not isinstance(tool, dict):
        raise ConfigError(path, "[tool] must be a TOML table")
    tool_table = cast(dict[str, object], tool)

    marker = tool_table.get("pyganini")
    if marker is None:
        if required:
            raise ConfigError(path, "missing [tool.pyganini] table")
        return False
    if not isinstance(marker, dict):
        raise ConfigError(path, "[tool.pyganini] must be a TOML table")
    marker_table = cast(dict[str, object], marker)
    if marker_table:
        keys = ", ".join(sorted(marker_table))
        raise ConfigError(path, f"unsupported [tool.pyganini] key(s): {keys}")
    return True
