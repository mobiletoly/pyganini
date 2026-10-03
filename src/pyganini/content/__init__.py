"""Optional trusted first-party HTML and Markdown content pages."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import cast

from starlette.requests import Request

from pyganini._render import AdditionalPage, PageMetadata
from pyganini._request_path import local_path

try:
    from markdown_it import MarkdownIt
    from mdit_py_plugins.anchors import anchors_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    import_module("linkify_it")
except ImportError as error:
    raise ImportError(
        "Content pages require the optional dependencies: install pyganini[content]"
    ) from error

_SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_METADATA_LIMIT = 16 * 1024
_BODY_LIMIT = 512 * 1024
_RENDERED_LIMIT = 2 * 1024 * 1024
_RECOGNIZED = frozenset({"page.json", "body.md", "body.html"})


@dataclass(frozen=True, slots=True)
class Config:
    """Application-owned trusted filesystem root."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.root), Path):
            raise TypeError("root must be a Path")


class ContentError(RuntimeError):
    """Operational failure with relative source evidence and a stable rule."""

    def __init__(self, path: str, rule: str) -> None:
        self.path = path
        self.rule = rule
        super().__init__(f"content {path}: {rule}")


def _label(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _kind(root: Path, path: Path) -> str:
    try:
        info = path.lstat()
    except OSError as error:
        raise ContentError(_label(root, path), "cannot inspect entry") from error
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ContentError(_label(root, path), "links and reparse points are forbidden")
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    if stat.S_ISREG(info.st_mode):
        return "file"
    raise ContentError(
        _label(root, path), "entry must be an ordinary file or directory"
    )


def _entries(root: Path, directory: Path) -> tuple[Path, ...]:
    if _kind(root, directory) != "directory":
        raise ContentError(_label(root, directory), "entry must be a directory")
    try:
        return tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    except OSError as error:
        raise ContentError(_label(root, directory), "cannot read directory") from error


def _read(root: Path, path: Path, limit: int) -> str:
    if _kind(root, path) != "file":
        raise ContentError(
            _label(root, path), "recognized source must be a regular file"
        )
    try:
        with path.open("rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ContentError(
                    _label(root, path), "opened source must be a regular file"
                )
            data = source.read(limit + 1)
    except OSError as error:
        raise ContentError(_label(root, path), "cannot read source") from error
    if len(data) > limit:
        raise ContentError(_label(root, path), f"source exceeds {limit} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeError as error:
        raise ContentError(_label(root, path), "source must be UTF-8") from error


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata field")
        result[key] = value
    return result


class _TrustedMarkdown(MarkdownIt):
    def validateLink(self, url: str) -> bool:
        return True


def _page(
    root: Path, directory: Path, entries: tuple[Path, ...]
) -> AdditionalPage | None:
    recognized = {entry.name for entry in entries if entry.name in _RECOGNIZED}
    if not recognized:
        return None
    if directory == root:
        raise ContentError(".", "root must not contain page sources")
    if "page.json" not in recognized or len(recognized & {"body.html", "body.md"}) != 1:
        raise ContentError(
            _label(root, directory),
            "page requires page.json and exactly one body.html or body.md",
        )
    metadata_path = directory / "page.json"
    metadata_text = _read(root, metadata_path, _METADATA_LIMIT)
    try:
        raw: object = json.loads(metadata_text, object_pairs_hook=_object)
        if not isinstance(raw, dict):
            raise ValueError("metadata must be an object")
        values = cast(dict[str, object], raw)
        if set(values) - {"title", "description"}:
            raise ValueError("unknown metadata field")
        title, description = values.get("title"), values.get("description", "")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a nonblank string")
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        metadata = PageMetadata(title, description)
    except ValueError as error:
        raise ContentError(
            _label(root, metadata_path), "invalid page metadata"
        ) from error
    body_path = directory / ("body.html" if "body.html" in recognized else "body.md")
    body = _read(root, body_path, _BODY_LIMIT)
    if not body.strip():
        raise ContentError(_label(root, body_path), "body must not be blank")
    if body_path.suffix == ".md":
        parser = _TrustedMarkdown("gfm-like", {"html": True})
        parser.use(tasklists_plugin, enabled=False)
        parser.use(anchors_plugin, min_level=1, max_level=6, permalink=False)
        try:
            body = parser.render(body)
        except Exception as error:
            raise ContentError(
                _label(root, body_path), "Markdown rendering failed"
            ) from error
        if len(body.encode("utf-8")) > _RENDERED_LIMIT:
            raise ContentError(
                _label(root, body_path), "rendered Markdown exceeds 2097152 bytes"
            )
    return AdditionalPage(
        f'<article class="pyganini-content">{body}</article>', metadata=metadata
    )


def check(root: Path) -> None:
    """Validate the complete trusted tree; this is not HTML sanitization."""
    if not isinstance(cast(object, root), Path):
        raise TypeError("root must be a Path")
    root = root.absolute()

    def walk(directory: Path) -> None:
        entries = _entries(root, directory)
        _page(root, directory, entries)
        for entry in entries:
            kind = _kind(root, entry)
            if kind == "directory":
                if _SEGMENT.fullmatch(entry.name) is None:
                    raise ContentError(
                        _label(root, entry),
                        "directory name is not a canonical content segment",
                    )
                walk(entry)

    walk(root)


class Pages:
    """A live resolver constructed with new(Config(...))."""

    __slots__ = ("_root",)

    def __init__(self, root: Path) -> None:
        self._root = root

    def resolve(self, request: Request) -> AdditionalPage | None:
        """Read one canonical GET/HEAD entry without walking other descendants."""
        if request.method not in {"GET", "HEAD"}:
            return None
        evidence = local_path(request.scope)
        if evidence is None:
            return None
        path, raw = evidence
        if path == "/" or (raw is not None and raw != path):
            return None
        segments = path[1:].split("/")
        if any(_SEGMENT.fullmatch(segment) is None for segment in segments):
            return None
        directory = self._root
        entries = _entries(self._root, directory)
        for segment in segments:
            directory = directory / segment
            try:
                kind = _kind(self._root, directory)
            except ContentError as error:
                if isinstance(error.__cause__, FileNotFoundError):
                    return None
                raise
            if kind != "directory":
                return None
            entries = _entries(self._root, directory)
        for entry in entries:
            _kind(self._root, entry)
        return _page(self._root, directory, entries)


def new(config: Config) -> Pages:
    """Check once at startup and capture an absolute trusted root."""
    if not isinstance(cast(object, config), Config):
        raise TypeError("config must be a Config")
    root = config.root.absolute()
    check(root)
    return Pages(root)


__all__ = ["Config", "ContentError", "Pages", "check", "new"]
