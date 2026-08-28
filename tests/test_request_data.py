from dataclasses import FrozenInstanceError
from io import BytesIO
from typing import BinaryIO

import anyio
import pytest
from starlette.applications import Starlette
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pyganini.request_data import (
    Body,
    BodyCapture,
    Form,
    FormCapture,
    Upload,
    _capture_request_data,  # pyright: ignore[reportPrivateUsage]
    capture_body,
    capture_form,
)


def test_public_request_data_values_are_frozen_and_preserve_form_order() -> None:
    upload = Upload("avatar.txt", "text/plain", b"avatar")
    form = Form(
        (
            ("name", "Ada"),
            ("avatar", upload),
            ("name", "Grace"),
        )
    )

    assert Body(b"payload").content == b"payload"
    assert form.values("name") == ("Ada", "Grace")
    assert form.uploads("avatar") == (upload,)
    assert form.values("missing") == ()
    assert form.uploads("missing") == ()
    with pytest.raises(FrozenInstanceError):
        upload.content = b"changed"  # type: ignore[misc]


def test_capture_fact_factories_and_direct_values_validate_limits() -> None:
    assert capture_body(max_bytes=10) == BodyCapture(10)
    assert capture_form(
        max_files=1,
        max_fields=2,
        max_part_size=64,
        max_upload_size=128,
    ) == FormCapture(1, 2, 64, 128)

    for value in (-1, True):
        with pytest.raises((TypeError, ValueError)):
            capture_body(max_bytes=value)
    with pytest.raises(ValueError):
        capture_form(max_files=1, max_fields=1, max_part_size=0, max_upload_size=1)


async def _capture_form_endpoint(request: Request) -> JSONResponse:
    form = await _capture_request_data(
        request,
        capture_form(
            max_files=1,
            max_fields=8,
            max_part_size=64,
            max_upload_size=128,
        ),
    )
    assert isinstance(form, Form)
    return JSONResponse(
        {
            "names": form.values("name"),
            "files": [
                {
                    "filename": upload.filename,
                    "content_type": upload.content_type,
                    "content": upload.content.decode(),
                }
                for upload in form.uploads("avatar")
            ],
        }
    )


async def _capture_body_endpoint(request: Request) -> JSONResponse:
    body = await _capture_request_data(request, capture_body(max_bytes=4))
    assert isinstance(body, Body)
    return JSONResponse({"body": body.content.decode()})


REQUEST_DATA_APP = Starlette(
    routes=[
        Route("/form", _capture_form_endpoint, methods=["POST"]),
        Route("/body", _capture_body_endpoint, methods=["POST"]),
    ]
)


def test_form_capture_preserves_repeated_values_and_materializes_uploads() -> None:
    with TestClient(REQUEST_DATA_APP) as client:
        response = client.post(
            "/form",
            content="name=Ada&name=Grace",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        multipart = client.post(
            "/form",
            data={"name": "Ada"},
            files={"avatar": ("avatar.txt", b"hello", "text/plain")},
        )

    assert response.json() == {"names": ["Ada", "Grace"], "files": []}
    assert multipart.json() == {
        "names": ["Ada"],
        "files": [
            {"filename": "avatar.txt", "content_type": "text/plain", "content": "hello"}
        ],
    }


def test_capture_limits_and_form_media_type_are_host_visible() -> None:
    with TestClient(REQUEST_DATA_APP, raise_server_exceptions=False) as client:
        too_large = client.post("/body", content=b"12345")
        unsupported = client.post("/form", content=b"{}")

    assert too_large.status_code == 413
    assert unsupported.status_code == 415


class _FormReader:
    def __init__(self, form: FormData) -> None:
        self.headers = Headers({"content-type": "multipart/form-data; boundary=x"})
        self._form = form

    async def form(self, **_: int) -> FormData:
        return self._form


class _CloseObserver(UploadFile):
    def __init__(self, file: BinaryIO, *, filename: str) -> None:
        super().__init__(file, filename=filename)
        self.close_attempts = 0

    async def close(self) -> None:
        self.close_attempts += 1
        await super().close()


class _ReadAndCloseFailure(_CloseObserver):
    async def read(self, size: int = -1) -> bytes:
        raise LookupError("primary read failure")

    async def close(self) -> None:
        self.close_attempts += 1
        raise RuntimeError("cleanup close failure")


class _CloseFailure(_CloseObserver):
    async def close(self) -> None:
        self.close_attempts += 1
        raise RuntimeError(f"cannot close {self.filename}")


class _BlockingRead(_CloseObserver):
    def __init__(self, file: BinaryIO, *, filename: str, started: anyio.Event) -> None:
        super().__init__(file, filename=filename)
        self.started = started

    async def read(self, size: int = -1) -> bytes:
        self.started.set()
        await anyio.sleep_forever()
        return b""


@pytest.mark.anyio
async def test_duplicate_uploads_close_once_and_primary_failures_keep_identity() -> (
    None
):
    first = _ReadAndCloseFailure(BytesIO(b"first"), filename="first.txt")
    second = _CloseObserver(BytesIO(b"second"), filename="second.txt")
    reader = _FormReader(
        FormData([("first", first), ("second", second), ("again", first)])
    )

    with pytest.raises(LookupError, match="primary read failure") as captured:
        await _capture_request_data(reader, FormCapture(2, 4, 64, 128))  # type: ignore[arg-type]

    assert first.close_attempts == 1
    assert second.close_attempts == 1
    assert any("cleanup close failure" in note for note in captured.value.__notes__)


@pytest.mark.anyio
async def test_cleanup_only_failures_are_grouped_in_close_order() -> None:
    first = _CloseFailure(BytesIO(b"first"), filename="first.txt")
    second = _CloseFailure(BytesIO(b"second"), filename="second.txt")
    reader = _FormReader(FormData([("first", first), ("second", second)]))

    with pytest.raises(ExceptionGroup, match="request-data cleanup failed") as captured:
        await _capture_request_data(reader, FormCapture(2, 4, 64, 128))  # type: ignore[arg-type]

    assert [str(error) for error in captured.value.exceptions] == [
        "cannot close first.txt",
        "cannot close second.txt",
    ]


@pytest.mark.anyio
async def test_cancellation_shields_upload_cleanup() -> None:
    started = anyio.Event()
    upload = _BlockingRead(BytesIO(b"payload"), filename="blocked.txt", started=started)
    reader = _FormReader(FormData([("avatar", upload)]))

    async def cancel_when_reading(scope: anyio.CancelScope) -> None:
        await started.wait()
        scope.cancel()

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(cancel_when_reading, scope)
            await _capture_request_data(reader, FormCapture(1, 1, 64, 128))  # type: ignore[arg-type]

    assert upload.close_attempts == 1
