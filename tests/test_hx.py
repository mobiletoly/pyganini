from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Scope

import pyganini
from pyganini import FragmentResponse, Page, hx

REQUEST_HEADERS = {
    "HEADER_BOOSTED": "HX-Boosted",
    "HEADER_CURRENT_URL": "HX-Current-URL",
    "HEADER_HISTORY_RESTORE_REQUEST": "HX-History-Restore-Request",
    "HEADER_PROMPT": "HX-Prompt",
    "HEADER_REQUEST": "HX-Request",
    "HEADER_TARGET": "HX-Target",
    "HEADER_TRIGGER": "HX-Trigger",
    "HEADER_TRIGGER_NAME": "HX-Trigger-Name",
}
RESPONSE_HEADERS = {
    "HEADER_LOCATION": "HX-Location",
    "HEADER_PUSH_URL": "HX-Push-Url",
    "HEADER_REDIRECT": "HX-Redirect",
    "HEADER_REFRESH": "HX-Refresh",
    "HEADER_REPLACE_URL": "HX-Replace-Url",
    "HEADER_RESELECT": "HX-Reselect",
    "HEADER_RETARGET": "HX-Retarget",
    "HEADER_RESWAP": "HX-Reswap",
    "HEADER_TRIGGER_AFTER_SETTLE": "HX-Trigger-After-Settle",
    "HEADER_TRIGGER_AFTER_SWAP": "HX-Trigger-After-Swap",
}


def _request(headers: dict[str, str] | None = None) -> Request:
    selected = {} if headers is None else headers
    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in selected.items()
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        },
    )
    return Request(scope)


def test_public_hx_surface_is_exact_and_documented() -> None:
    assert {
        name: getattr(hx, name) for name in (*REQUEST_HEADERS, *RESPONSE_HEADERS)
    } == {**REQUEST_HEADERS, **RESPONSE_HEADERS}
    assert set(hx.__all__) == {
        *REQUEST_HEADERS,
        *RESPONSE_HEADERS,
        "is_request",
        "is_boosted",
        "is_history_restore_request",
        "current_url",
        "prompt",
        "target",
        "trigger_id",
        "trigger_name",
    }
    assert pyganini.hx is hx
    assert hx.__doc__
    for old_name in (
        "BOOSTED",
        "CURRENT_URL",
        "HISTORY_RESTORE_REQUEST",
        "LOCATION",
        "PROMPT",
        "PUSH_URL",
        "REDIRECT",
        "REFRESH",
        "REPLACE_URL",
        "REQUEST",
        "RESELECT",
        "RESWAP",
        "RETARGET",
        "TARGET",
        "TRIGGER",
        "TRIGGER_AFTER_SETTLE",
        "TRIGGER_AFTER_SWAP",
        "TRIGGER_NAME",
    ):
        assert not hasattr(hx, old_name)
    for helper in (
        hx.is_request,
        hx.is_boosted,
        hx.is_history_restore_request,
        hx.current_url,
        hx.prompt,
        hx.target,
        hx.trigger_id,
        hx.trigger_name,
    ):
        assert helper.__doc__


@pytest.mark.parametrize(
    ("helper", "header"),
    [
        (hx.is_request, "HX-Request"),
        (hx.is_boosted, "HX-Boosted"),
        (hx.is_history_restore_request, "HX-History-Restore-Request"),
    ],
)
def test_boolean_request_helpers_accept_only_exact_true(
    helper: Callable[[Request], bool],
    header: str,
) -> None:
    for value in (None, "", "false", "TRUE", "True", " true", "true "):
        headers: dict[str, str] = {} if value is None else {header: value}
        assert not helper(_request(headers))
    assert helper(_request({header: "true"}))


def test_text_request_helpers_return_first_value_or_empty() -> None:
    request = _request(
        {
            "HX-Current-URL": "https://example.test/users",
            "HX-Prompt": "confirmed",
            "HX-Target": "users-table",
            "HX-Trigger": "save-button",
            "HX-Trigger-Name": "save",
        }
    )
    assert hx.current_url(request) == "https://example.test/users"
    assert hx.prompt(request) == "confirmed"
    assert hx.target(request) == "users-table"
    assert hx.trigger_id(request) == "save-button"
    assert hx.trigger_name(request) == "save"
    empty = _request()
    assert hx.current_url(empty) == ""
    assert hx.prompt(empty) == ""
    assert hx.target(empty) == ""
    assert hx.trigger_id(empty) == ""
    assert hx.trigger_name(empty) == ""


@pytest.mark.parametrize("header", tuple(RESPONSE_HEADERS.values()))
def test_response_constants_work_with_existing_response_owners(header: str) -> None:
    assert FragmentResponse(headers={header: "value"}).headers[header] == "value"
    assert Page(headers={header: "value"}).headers[header] == "value"
    response = Response(headers={header: "value"})
    assert response.headers[header] == "value"


async def _read_form(request: Request) -> JSONResponse:
    upload: UploadFile | None = None
    values: list[str] = []
    content = b""
    async with request.form(
        max_files=8,
        max_fields=64,
        max_part_size=1_048_576,
    ) as form:
        values = [value for value in form.getlist("name") if isinstance(value, str)]
        candidate = form.get("avatar")
        if isinstance(candidate, UploadFile):
            upload = candidate
            content = await candidate.read()
    return JSONResponse(
        {
            "names": values,
            "filename": None if upload is None else upload.filename,
            "content": content.decode("ascii"),
            "closed": upload is not None and upload.file.closed,
        }
    )


async def _limited_form(request: Request) -> Response:
    try:
        async with request.form(
            max_files=1,
            max_fields=1,
            max_part_size=16,
        ) as form:
            return JSONResponse({"values": form.getlist("name")})
    except HTTPException as error:
        return PlainTextResponse(str(error.detail), status_code=error.status_code)


FORM_APP = Starlette(
    routes=[
        Route("/read", _read_form, methods=["POST"]),
        Route("/limited", _limited_form, methods=["POST"]),
    ]
)


def test_starlette_urlencoded_forms_keep_repeated_values() -> None:
    with TestClient(FORM_APP) as client:
        response = client.post(
            "/read",
            content="name=Ada&name=Grace",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "names": ["Ada", "Grace"],
        "filename": None,
        "content": "",
        "closed": False,
    }


def test_starlette_multipart_forms_read_uploads_inside_context_and_close_them() -> None:
    with TestClient(FORM_APP) as client:
        response = client.post(
            "/read",
            data={"name": "Ada"},
            files={"avatar": ("avatar.txt", b"avatar-bytes", "text/plain")},
        )
    assert response.status_code == 200
    assert response.json() == {
        "names": ["Ada"],
        "filename": "avatar.txt",
        "content": "avatar-bytes",
        "closed": True,
    }


def test_starlette_form_limits_reject_field_count_and_part_size() -> None:
    with TestClient(FORM_APP) as client:
        too_many_fields = client.post(
            "/limited",
            content="first=1&second=2",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        too_large_field = client.post(
            "/limited",
            content="name=123456789012345",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert too_many_fields.status_code == 400
    assert "Too many fields" in too_many_fields.text
    assert too_large_field.status_code == 400
    assert "Field exceeded maximum size" in too_large_field.text


def test_starlette_multipart_limits_reject_file_count() -> None:
    with TestClient(FORM_APP) as client:
        response = client.post(
            "/limited",
            files=[
                ("first", ("first.txt", b"one", "text/plain")),
                ("second", ("second.txt", b"two", "text/plain")),
            ],
        )
    assert response.status_code == 400
    assert "Too many files" in response.text


def test_malformed_multipart_input_stays_a_starlette_parser_error() -> None:
    with TestClient(FORM_APP) as client:
        response = client.post(
            "/read",
            content=b"not-a-multipart-body",
            headers={"content-type": "multipart/form-data"},
        )
    assert response.status_code == 400
    assert response.text == "Missing boundary in multipart."


def _checker_run(
    checker: str, application: Path, sample: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(application)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if checker == "pyright":
        (application / "pyrightconfig.json").write_text(
            '{"typeCheckingMode": "strict", "include": ["sample.py"]}\n',
            encoding="ascii",
        )
        command = [str(Path(sys.executable).parent / "pyright"), str(sample)]
    else:
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--python-version",
            "3.13",
            str(sample),
        ]
    return subprocess.run(
        command,
        cwd=application,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _sample_line(sample: Path, marker: str) -> int:
    return next(
        number
        for number, line in enumerate(
            sample.read_text(encoding="ascii").splitlines(), 1
        )
        if marker in line
    )


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_hx_public_annotations_pass_both_locked_type_checkers(
    tmp_path: Path, checker: str
) -> None:
    application = tmp_path / "typing"
    application.mkdir()
    valid = application / "valid.py"
    valid.write_text(
        "from pyganini import hx\n"
        "from starlette.requests import Request\n"
        "def read(request: Request) -> tuple[bool, str, str]:\n"
        "    return (hx.is_request(request), hx.current_url(request), "
        "hx.HEADER_RETARGET)\n",
        encoding="ascii",
    )
    valid_result = _checker_run(checker, application, valid)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr

    invalid = application / "sample.py"
    invalid.write_text(
        "from pyganini import hx\n"
        "from starlette.requests import Request\n"
        "def wrong_request(value: object) -> None:\n"
        "    hx.is_request(value)  # WRONG_REQUEST\n"
        "def wrong_return(request: Request) -> None:\n"
        "    value: int = hx.current_url(request)  # WRONG_RETURN\n",
        encoding="ascii",
    )
    invalid_result = _checker_run(checker, application, invalid)
    output = invalid_result.stdout + invalid_result.stderr
    assert invalid_result.returncode != 0
    for marker in ("WRONG_REQUEST", "WRONG_RETURN"):
        assert f":{_sample_line(invalid, marker)}:" in output
