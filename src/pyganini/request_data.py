"""Explicit immutable request data for captured action handlers."""

# pyright: reportUnnecessaryIsInstance=false, reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass

import anyio
from python_multipart.multipart import parse_options_header
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request

__all__ = [
    "Body",
    "BodyCapture",
    "Form",
    "FormCapture",
    "FormItem",
    "Upload",
    "capture_body",
    "capture_form",
]

type FormItem = tuple[str, str | Upload]

_UPLOAD_READ_SIZE = 64 * 1024


def _require_integer(value: object, *, field: str, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class Upload:
    """One fully materialized upload with no live resource."""

    filename: str | None
    content_type: str | None
    content: bytes

    def __post_init__(self) -> None:
        if self.filename is not None and not isinstance(self.filename, str):
            raise TypeError("filename must be a string or None")
        if self.content_type is not None and not isinstance(self.content_type, str):
            raise TypeError("content_type must be a string or None")
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes")


@dataclass(frozen=True, slots=True)
class Body:
    """One fully materialized request body."""

    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes")


@dataclass(frozen=True, slots=True)
class Form:
    """Ordered text and immutable upload values from one parsed form."""

    items: tuple[FormItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("items must be a tuple")
        for item in self.items:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], (str, Upload))
            ):
                raise TypeError("items must contain (str, str | Upload) pairs")

    def values(self, field: str) -> tuple[str, ...]:
        """Return textual values for one field in source order."""
        if not isinstance(field, str):
            raise TypeError("field must be a string")
        return tuple(
            value
            for name, value in self.items
            if name == field and isinstance(value, str)
        )

    def uploads(self, field: str) -> tuple[Upload, ...]:
        """Return immutable uploads for one field in source order."""
        if not isinstance(field, str):
            raise TypeError("field must be a string")
        return tuple(
            value
            for name, value in self.items
            if name == field and isinstance(value, Upload)
        )


@dataclass(frozen=True, slots=True)
class BodyCapture:
    """Declaration for bounded raw-body capture."""

    max_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_bytes",
            _require_integer(self.max_bytes, field="max_bytes"),
        )


@dataclass(frozen=True, slots=True)
class FormCapture:
    """Declaration for bounded URL-encoded or multipart capture."""

    max_files: int
    max_fields: int
    max_part_size: int
    max_upload_size: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_files",
            _require_integer(self.max_files, field="max_files"),
        )
        object.__setattr__(
            self,
            "max_fields",
            _require_integer(self.max_fields, field="max_fields"),
        )
        object.__setattr__(
            self,
            "max_part_size",
            _require_integer(self.max_part_size, field="max_part_size", positive=True),
        )
        object.__setattr__(
            self,
            "max_upload_size",
            _require_integer(
                self.max_upload_size,
                field="max_upload_size",
                positive=True,
            ),
        )


def capture_body(*, max_bytes: int) -> BodyCapture:
    """Declare bounded raw-body capture for one synchronous action."""
    return BodyCapture(max_bytes=max_bytes)


def capture_form(
    *,
    max_files: int,
    max_fields: int,
    max_part_size: int,
    max_upload_size: int,
) -> FormCapture:
    """Declare bounded URL-encoded or multipart capture for one sync action."""
    return FormCapture(
        max_files=max_files,
        max_fields=max_fields,
        max_part_size=max_part_size,
        max_upload_size=max_upload_size,
    )


def _capture_literal(capture: BodyCapture | FormCapture) -> tuple[str, tuple[int, ...]]:
    if isinstance(capture, BodyCapture):
        return "body", (capture.max_bytes,)
    return (
        "form",
        (
            capture.max_files,
            capture.max_fields,
            capture.max_part_size,
            capture.max_upload_size,
        ),
    )


def _content_type(request: Request) -> bytes:
    raw = request.headers.get("content-type", "")
    value, _ = parse_options_header(raw)
    return value


async def _capture_body(request: Request, declaration: BodyCapture) -> Body:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > declaration.max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    "request body exceeds the configured max_bytes limit "
                    f"({declaration.max_bytes})"
                ),
            )
        content.extend(chunk)
    return Body(bytes(content))


def _distinct_uploads(parsed: FormData) -> tuple[tuple[str, UploadFile], ...]:
    distinct: list[tuple[str, UploadFile]] = []
    seen: set[int] = set()
    for field, value in parsed.multi_items():
        if isinstance(value, UploadFile) and id(value) not in seen:
            seen.add(id(value))
            distinct.append((field, value))
    return tuple(distinct)


async def _close_uploads(
    uploads: tuple[tuple[str, UploadFile], ...],
) -> tuple[tuple[str, UploadFile, Exception], ...]:
    failures: list[tuple[str, UploadFile, Exception]] = []
    with anyio.CancelScope(shield=True):
        for field, upload in uploads:
            try:
                await upload.close()
            except Exception as error:
                failures.append((field, upload, error))
    return tuple(failures)


def _add_cleanup_notes(
    primary: BaseException,
    failures: tuple[tuple[str, UploadFile, Exception], ...],
) -> None:
    for field, upload, error in failures:
        primary.add_note(
            "request-data cleanup failed for "
            f"field {field!r}, upload {upload.filename!r}: "
            f"{type(error).__name__}: {error}"
        )


async def _capture_form(request: Request, declaration: FormCapture) -> Form:
    media_type = _content_type(request)
    if media_type not in {
        b"multipart/form-data",
        b"application/x-www-form-urlencoded",
    }:
        raise HTTPException(
            status_code=415,
            detail="request form content type must be multipart/form-data or "
            "application/x-www-form-urlencoded",
        )

    parsed = await request.form(
        max_files=declaration.max_files,
        max_fields=declaration.max_fields,
        max_part_size=declaration.max_part_size,
    )
    uploads = _distinct_uploads(parsed)
    materialized: dict[int, Upload] = {}
    values: list[FormItem] = []
    try:
        for field, value in parsed.multi_items():
            if isinstance(value, UploadFile):
                key = id(value)
                upload = materialized.get(key)
                if upload is None:
                    content = bytearray()
                    while True:
                        remaining = declaration.max_upload_size - len(content)
                        chunk = await value.read(
                            min(_UPLOAD_READ_SIZE, max(1, remaining + 1))
                        )
                        if not chunk:
                            break
                        if len(content) + len(chunk) > declaration.max_upload_size:
                            raise HTTPException(
                                status_code=413,
                                detail=(
                                    f"upload for field {field!r} and filename "
                                    f"{value.filename!r} exceeds the configured "
                                    "max_upload_size limit "
                                    f"({declaration.max_upload_size})"
                                ),
                            )
                        content.extend(chunk)
                    upload = Upload(value.filename, value.content_type, bytes(content))
                    materialized[key] = upload
                values.append((field, upload))
            else:
                values.append((field, value))
    except BaseException as primary:
        _add_cleanup_notes(primary, await _close_uploads(uploads))
        raise

    cleanup_failures = await _close_uploads(uploads)
    if cleanup_failures:
        raise ExceptionGroup(
            "request-data cleanup failed",
            [error for _, _, error in cleanup_failures],
        )
    return Form(tuple(values))


async def _capture_request_data(
    request: Request,
    declaration: BodyCapture | FormCapture,
) -> Body | Form:
    """Materialize one declaration on the ASGI side of dispatch."""
    if isinstance(declaration, BodyCapture):
        return await _capture_body(request, declaration)
    return await _capture_form(request, declaration)
