"""Original graph-local HTTP path evidence, without route or content discovery."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import unquote_to_bytes

from pyganini._url_binding import normalize_base_path

_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


def local_path(scope: Mapping[str, object]) -> tuple[str, str | None] | None:
    """Derive a local decoded path and optional unchanged raw remainder."""
    path = scope.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    try:
        base = unquote_to_bytes(normalize_base_path(scope.get("root_path", ""))).decode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError):
        return None
    stripped = bool(base and (path == base or path.startswith(base + "/")))
    decoded = (path[len(base) :] or "/") if stripped else path
    raw = scope.get("raw_path")
    if raw is None:
        return decoded, None
    if not isinstance(raw, bytes):
        return None
    try:
        original = raw.decode("utf-8")
        if (
            _BAD_ESCAPE.search(original)
            or unquote_to_bytes(original).decode("utf-8") != path
        ):
            return None
    except UnicodeError:
        return None
    if stripped:
        # Each literal byte or percent triplet contributes one decoded byte.
        # Count decoded prefix bytes so escaped host separators stay in the host.
        boundary = 0
        for _ in range(len(base.encode("utf-8"))):
            boundary += 3 if raw[boundary : boundary + 1] == b"%" else 1
        original = raw[boundary:].decode("utf-8") or "/"
    return decoded, original
