from collections.abc import Awaitable
from dataclasses import FrozenInstanceError
from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO, cast

import anyio
import pytest
from starlette.applications import Starlette
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from foundation_probes.callable_invocation import (
    RequestData,
    UploadedPart,
    capture_request_data,
    invoke_callable,
)


async def capture_endpoint(request: Request) -> JSONResponse:
    data = await capture_request_data(request)

    def sync_action(request_data: RequestData) -> dict[str, Any]:
        files = [
            {
                "field": item.field,
                "filename": item.filename,
                "content_type": item.content_type,
                "content": item.content.decode(),
            }
            for item in request_data.form
            if isinstance(item, UploadedPart)
        ]
        return {
            "body": request_data.body.decode(errors="replace"),
            "names": request_data.values("name"),
            "files": files,
        }

    result = await invoke_callable(sync_action, data)
    repeated = await request.body()
    result["repeated_body_matches"] = repeated == data.body
    return JSONResponse(result)


APP = Starlette(routes=[Route("/capture", capture_endpoint, methods=["POST"])])


def test_empty_body_is_captured_before_sync_action() -> None:
    with TestClient(APP) as client:
        response = client.post("/capture")
    assert response.json() == {
        "body": "",
        "names": [],
        "files": [],
        "repeated_body_matches": True,
    }


def test_urlencoded_form_and_repeated_body_access() -> None:
    with TestClient(APP) as client:
        response = client.post(
            "/capture",
            content="name=Ada&name=Grace",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.json()["names"] == ["Ada", "Grace"]
    assert response.json()["repeated_body_matches"] is True


def test_small_multipart_form_is_fully_materialized_before_offload() -> None:
    with TestClient(APP) as client:
        response = client.post(
            "/capture",
            data={"name": "Ada"},
            files={"avatar": ("a.txt", b"hello", "text/plain")},
        )
    assert response.json()["names"] == ["Ada"]
    assert response.json()["files"] == [
        {
            "field": "avatar",
            "filename": "a.txt",
            "content_type": "text/plain",
            "content": "hello",
        }
    ]


def test_malformed_multipart_form_is_rejected_by_starlette_parser() -> None:
    with TestClient(APP, raise_server_exceptions=False) as client:
        response = client.post(
            "/capture",
            content=b"not-a-multipart-body",
            headers={"content-type": "multipart/form-data"},
        )
    assert response.status_code == 400
    assert response.text == "Missing boundary in multipart."


class FailingReader:
    async def body(self) -> bytes:
        return b"input"

    def form(self) -> Awaitable[FormData]:
        async def fail() -> FormData:
            raise ValueError("parser failed")

        return fail()


class FormReader:
    def __init__(self, form: FormData) -> None:
        self._form = form

    async def body(self) -> bytes:
        return b"input"

    def form(self) -> Awaitable[FormData]:
        async def result() -> FormData:
            return self._form

        return result()


class FailingUpload(UploadFile):
    closed = False

    async def read(self, size: int = -1) -> bytes:
        raise ValueError("upload read failed")

    async def close(self) -> None:
        self.closed = True
        await super().close()


class CloseObserver(UploadFile):
    close_attempts = 0

    async def close(self) -> None:
        self.close_attempts += 1
        await super().close()


class ReadAndCloseFailure(UploadFile):
    close_attempts = 0

    async def read(self, size: int = -1) -> bytes:
        raise LookupError("primary read failure")

    async def close(self) -> None:
        self.close_attempts += 1
        raise RuntimeError("cleanup close failure")


class CloseFailure(UploadFile):
    close_attempts = 0

    async def close(self) -> None:
        self.close_attempts += 1
        raise RuntimeError(f"cannot close {self.filename}")


class BlockingReadUpload(UploadFile):
    def __init__(self, file: BinaryIO, entered: anyio.Event) -> None:
        super().__init__(file, filename="blocking.txt")
        self.entered = entered
        self.close_attempts = 0

    async def read(self, size: int = -1) -> bytes:
        self.entered.set()
        await anyio.sleep_forever()
        return b""

    async def close(self) -> None:
        self.close_attempts += 1
        await super().close()


@pytest.mark.anyio
async def test_form_parser_exception_crosses_capture_boundary() -> None:
    with pytest.raises(ValueError, match="parser failed"):
        await capture_request_data(FailingReader())


@pytest.mark.anyio
async def test_materialized_upload_is_closed_after_capture() -> None:
    backing = SpooledTemporaryFile[bytes]()
    backing.write(b"content")
    backing.seek(0)
    upload = UploadFile(
        cast("BinaryIO", backing),
        filename="file.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    data = await capture_request_data(FormReader(FormData([("file", upload)])))
    assert data.form == (
        UploadedPart(
            field="file",
            filename="file.txt",
            content_type="text/plain",
            content=b"content",
        ),
    )
    assert backing.closed


@pytest.mark.anyio
async def test_uploads_are_closed_when_materialization_fails() -> None:
    backing = SpooledTemporaryFile[bytes]()
    upload = FailingUpload(cast("BinaryIO", backing), filename="failed.txt")
    with pytest.raises(ValueError, match="upload read failed"):
        await capture_request_data(FormReader(FormData([("file", upload)])))
    assert upload.closed
    assert backing.closed


@pytest.mark.anyio
async def test_request_data_value_is_immutable() -> None:
    data = RequestData(body=b"", form=())
    with pytest.raises(FrozenInstanceError):
        data.body = b"changed"  # type: ignore[misc]


@pytest.mark.anyio
async def test_all_distinct_uploads_close_after_successful_capture() -> None:
    first_backing = SpooledTemporaryFile[bytes]()
    first_backing.write(b"first")
    first_backing.seek(0)
    second_backing = SpooledTemporaryFile[bytes]()
    second_backing.write(b"second")
    second_backing.seek(0)
    first = CloseObserver(cast("BinaryIO", first_backing), filename="first.txt")
    second = CloseObserver(cast("BinaryIO", second_backing), filename="second.txt")

    data = await capture_request_data(
        FormReader(FormData([("first", first), ("second", second)]))
    )

    assert [item.content for item in data.form if isinstance(item, UploadedPart)] == [
        b"first",
        b"second",
    ]
    assert first.close_attempts == 1
    assert second.close_attempts == 1
    assert first_backing.closed
    assert second_backing.closed


@pytest.mark.anyio
async def test_primary_failure_survives_cleanup_failures_and_later_closes() -> None:
    first = ReadAndCloseFailure(BytesIO(b"first"), filename="first.txt")
    second_backing = SpooledTemporaryFile[bytes]()
    second = CloseObserver(cast("BinaryIO", second_backing), filename="second.txt")

    with pytest.raises(LookupError, match="primary read failure") as captured:
        await capture_request_data(
            FormReader(FormData([("first", first), ("second", second)]))
        )

    notes = getattr(captured.value, "__notes__", ())
    assert any("cleanup close failure" in note for note in notes)
    assert first.close_attempts == 1
    assert second.close_attempts == 1
    assert second_backing.closed


@pytest.mark.anyio
async def test_cleanup_only_failures_are_grouped_after_all_close_attempts() -> None:
    first = CloseFailure(BytesIO(b"first"), filename="first.txt")
    second = CloseFailure(BytesIO(b"second"), filename="second.txt")

    with pytest.raises(ExceptionGroup, match="request-data cleanup failed") as captured:
        await capture_request_data(
            FormReader(FormData([("first", first), ("second", second)]))
        )

    assert [str(error) for error in captured.value.exceptions] == [
        "cannot close first.txt",
        "cannot close second.txt",
    ]
    assert first.close_attempts == 1
    assert second.close_attempts == 1


@pytest.mark.anyio
async def test_cancellation_during_upload_read_shields_cleanup() -> None:
    entered = anyio.Event()
    backing = SpooledTemporaryFile[bytes](max_size=1)
    backing.write(b"rolled-to-disk")
    backing.seek(0)
    upload = BlockingReadUpload(cast("BinaryIO", backing), entered)

    async def cancel_when_entered(scope: anyio.CancelScope) -> None:
        await entered.wait()
        scope.cancel()

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(cancel_when_entered, scope)
            await capture_request_data(FormReader(FormData([("file", upload)])))

    assert upload.close_attempts == 1
    assert backing.closed


@pytest.mark.anyio
async def test_duplicate_upload_reference_closes_once() -> None:
    backing = SpooledTemporaryFile[bytes]()
    upload = CloseObserver(cast("BinaryIO", backing), filename="duplicate.txt")

    await capture_request_data(
        FormReader(FormData([("first", upload), ("second", upload)]))
    )

    assert upload.close_attempts == 1
    assert backing.closed
