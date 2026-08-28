import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal, Protocol, cast

from anyio import CancelScope
from anyio.to_thread import run_sync
from starlette.datastructures import FormData, UploadFile

CallableKind = Literal["async", "sync"]


class CallableRejection(TypeError):
    pass


def classify_callable(callable_value: Callable[..., object]) -> CallableKind:
    """Classify without executing application code."""
    target: object = callable_value
    while isinstance(target, partial):
        target = target.func
    if not inspect.isfunction(target) and not inspect.ismethod(target):
        call_descriptor = inspect.getattr_static(type(target), "__call__", None)
        if call_descriptor is None:
            raise CallableRejection("callable phase: value is not callable")
        if not inspect.isfunction(call_descriptor):
            raise CallableRejection(
                "callable phase: callable-instance __call__ descriptor is unsupported"
            )
        target = call_descriptor
    if inspect.isasyncgenfunction(target):
        raise CallableRejection(
            "callable phase: async-generator route callable is unsupported"
        )
    if inspect.iscoroutinefunction(target):
        return "async"
    return "sync"


async def invoke_callable[T](
    callable_value: Callable[..., T | Awaitable[T]],
    *args: object,
    **kwargs: object,
) -> T:
    """Invoke async directly and sync outside the event-loop thread."""
    kind = classify_callable(callable_value)
    if kind == "async":
        initial = callable_value(*args, **kwargs)
    else:
        call = partial(callable_value, *args, **kwargs)
        initial = await run_sync(call, abandon_on_cancel=True)
    if inspect.isawaitable(initial):
        return await cast("Awaitable[T]", initial)
    return initial


@dataclass(frozen=True, slots=True)
class UploadedPart:
    field: str
    filename: str | None
    content_type: str | None
    content: bytes


FormValue = tuple[str, str] | UploadedPart


@dataclass(frozen=True, slots=True)
class RequestData:
    body: bytes
    form: tuple[FormValue, ...]

    def values(self, field: str) -> tuple[str, ...]:
        return tuple(
            item[1]
            for item in self.form
            if isinstance(item, tuple) and item[0] == field
        )


class RequestReader(Protocol):
    async def body(self) -> bytes: ...

    def form(self) -> Awaitable[FormData]: ...


def _distinct_uploads(parsed: FormData) -> tuple[tuple[str, UploadFile], ...]:
    uploads: list[tuple[str, UploadFile]] = []
    seen: set[int] = set()
    for field, value in parsed.multi_items():
        if isinstance(value, UploadFile) and id(value) not in seen:
            seen.add(id(value))
            uploads.append((field, value))
    return tuple(uploads)


async def _close_uploads(
    uploads: tuple[tuple[str, UploadFile], ...],
) -> tuple[tuple[str, UploadFile, Exception], ...]:
    failures: list[tuple[str, UploadFile, Exception]] = []
    with CancelScope(shield=True):
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


async def capture_request_data(request: RequestReader) -> RequestData:
    """Read body and parsed form on the ASGI thread before sync offload."""
    body = await request.body()
    parsed = await request.form()
    uploads = _distinct_uploads(parsed)
    values: list[FormValue] = []
    try:
        for field, value in parsed.multi_items():
            if isinstance(value, UploadFile):
                values.append(
                    UploadedPart(
                        field=field,
                        filename=value.filename,
                        content_type=value.content_type,
                        content=await value.read(),
                    )
                )
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
    return RequestData(body=body, form=tuple(values))


def immutable_headers(scope: Mapping[str, Any]) -> tuple[tuple[bytes, bytes], ...]:
    return tuple(scope.get("headers", ()))
