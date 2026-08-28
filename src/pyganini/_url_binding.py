"""Shared pure URL-segment binding used by generated and request navigation."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote


def quote_segment(label: str, value: object) -> str:
    """Quote one validated route parameter using Pyganini's URL contract."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be str")
    if value == "":
        raise ValueError(f"{label} must not be empty")
    if value in {".", ".."}:
        raise ValueError(f"{label} must not be '.' or '..'")
    if "/" in value or chr(92) in value:
        raise ValueError(f"{label} must not contain '/' or '" + chr(92) + "'")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} must not contain ASCII control characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} must contain valid Unicode text") from error
    return quote(value, safe="")


def bind_pattern(pattern: str, path_params: Mapping[str, object]) -> str:
    """Bind one generated route pattern to matched path parameter values."""
    if pattern == "/":
        return "/"
    values: list[str] = []
    for segment in pattern[1:].split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            if name not in path_params:
                raise ValueError(f"navigation parameter {name!r} is absent")
            values.append(
                quote_segment(f"navigation parameter {name!r}", path_params[name])
            )
        else:
            values.append(segment)
    return "/" + "/".join(values)


def normalize_base_path(base_path: object) -> str:
    """Normalize one decoded ASGI base path through the URL-helper contract."""
    if not isinstance(base_path, str):
        raise TypeError("base_path must be str")
    if base_path in {"", "/"}:
        return ""
    if all(character == "/" for character in base_path):
        raise ValueError("base_path must not contain empty path segments")
    normalized = base_path if base_path.startswith("/") else "/" + base_path
    normalized = normalized.rstrip("/")
    segments = normalized[1:].split("/")
    if any(segment == "" for segment in segments):
        raise ValueError("base_path must not contain empty path segments")
    quoted = tuple(
        quote_segment(f"base_path segment {index}", segment)
        for index, segment in enumerate(segments, start=1)
    )
    return "/" + "/".join(quoted)


def bind_external_pattern(
    pattern: str,
    path_params: Mapping[str, object],
    *,
    base_path: object,
) -> str:
    """Bind a graph-local pattern in one decoded external base path."""
    return normalize_base_path(base_path) + bind_pattern(pattern, path_params)


__all__ = (
    "bind_external_pattern",
    "bind_pattern",
    "normalize_base_path",
    "quote_segment",
)
