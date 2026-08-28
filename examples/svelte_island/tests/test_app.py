"""HTTP contract for the bounded Svelte island."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

import pytest
from httpx2 import Response
from pyganini import csrf
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.main import create_app

from .client import ExampleClient, as_example_client


@pytest.fixture
def client() -> Iterator[ExampleClient]:
    with TestClient(create_app()) as test_client:
        yield as_example_client(test_client)


def _csrf(client: ExampleClient) -> tuple[str, str]:
    response = client.get("/")
    token_prefix = f'<meta name="{csrf.META_NAME}" content="'
    token = response.text.split(token_prefix, 1)[1].split('"', 1)[0]
    cookie = response.cookies[csrf.DEFAULT_COOKIE_NAME]
    return token, cookie


def _post(
    client: ExampleClient,
    body: bytes,
    *,
    token: str | None,
    cookie: str,
    content_type: str = "application/json",
) -> Response:
    headers = {
        "Content-Type": content_type,
        "Cookie": f"{csrf.DEFAULT_COOKIE_NAME}={cookie}",
    }
    if token is not None:
        headers[csrf.HEADER_NAME] = token
    return client.post("/save", content=body, headers=headers)


def test_page_and_assets_are_server_owned(client: ExampleClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert 'data-client-island="project-editor"' in response.text
    assert 'data-project-name="Pyganini island"' in response.text
    assert 'data-project-pinned="false"' in response.text
    assert 'data-save-url="/save"' in response.text
    assert 'data-cancel-url="/about"' in response.text
    assert 'hx-boost:inherited="true"' in response.text
    assert f'<meta name="{csrf.META_NAME}"' in response.text
    assert csrf.DEFAULT_COOKIE_NAME in response.cookies
    assert "https://cdn" not in response.text

    for logical in ("app.css", "app.js", "vendor/htmx.min.js"):
        match = re.search(
            rf'<(?:link|script) data-asset="{re.escape(logical)}"[^>]+'
            rf'(?:href|src)="([^"]+)"',
            response.text,
        )
        assert match is not None
        path = match.group(1)
        asset = client.get(path)
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"

    missing = client.get("/assets/missing.js")
    assert missing.status_code == 404
    assert "cache-control" not in missing.headers


def test_generated_urls_follow_the_application_mount() -> None:
    host = Starlette(routes=[Mount("/demo", app=create_app())])
    with TestClient(host) as test_client:
        response = test_client.get("/demo/")
    assert 'data-save-url="/demo/save"' in response.text
    assert 'data-cancel-url="/demo/about"' in response.text
    assert 'href="/demo/assets/' in response.text


def test_save_contract_and_persistence(client: ExampleClient) -> None:
    token, cookie = _csrf(client)
    response = _post(
        client,
        b'{"name":"  Calm Svelte editor  ","pinned":true}',
        token=token,
        cookie=cookie,
        content_type="Application/JSON; charset=utf-8",
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "project": {"name": "Calm Svelte editor", "pinned": True}
    }
    page = client.get("/")
    assert 'data-project-name="Calm Svelte editor"' in page.text
    assert 'data-project-pinned="true"' in page.text


@pytest.mark.parametrize(
    ("body", "content_type", "token_mode", "status", "payload"),
    [
        (
            b'{"name":"A","pinned":false}',
            "application/json",
            "missing",
            403,
            {"error": "forbidden"},
        ),
        (
            b'{"name":"A","pinned":false}',
            "application/json",
            "invalid",
            403,
            {"error": "forbidden"},
        ),
        (
            b'{"name":"A","pinned":false}',
            "text/plain",
            "valid",
            415,
            {"error": "unsupported media type"},
        ),
        (b"{", "application/json", "valid", 400, {"error": "bad request"}),
        (b"[]", "application/json", "valid", 400, {"error": "bad request"}),
        (b"null", "application/json", "valid", 400, {"error": "bad request"}),
        (b'"value"', "application/json", "valid", 400, {"error": "bad request"}),
        (
            b'{"name":"A","pinned":false} trailing',
            "application/json",
            "valid",
            400,
            {"error": "bad request"},
        ),
        (
            b'{"name":"\xff","pinned":false}',
            "application/json",
            "valid",
            400,
            {"error": "bad request"},
        ),
        (b'{"name":"A"}', "application/json", "valid", 400, {"error": "bad request"}),
        (
            b'{"name":"A","pinned":false,"extra":1}',
            "application/json",
            "valid",
            400,
            {"error": "bad request"},
        ),
        (
            b'{"name":1,"pinned":false}',
            "application/json",
            "valid",
            400,
            {"error": "bad request"},
        ),
        (
            b'{"name":"A","pinned":0}',
            "application/json",
            "valid",
            400,
            {"error": "bad request"},
        ),
        (
            b'{"name":"   ","pinned":false}',
            "application/json",
            "valid",
            422,
            {"errors": {"name": "Enter a project name."}},
        ),
    ],
)
def test_save_failures_do_not_mutate(
    client: ExampleClient,
    body: bytes,
    content_type: str,
    token_mode: str,
    status: int,
    payload: object,
) -> None:
    token, cookie = _csrf(client)
    response = _post(
        client,
        body,
        token=token
        if token_mode == "valid"
        else ("invalid" if token_mode == "invalid" else None),
        cookie=cookie,
        content_type=content_type,
    )
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == payload
    assert 'data-project-name="Pyganini island"' in client.get("/").text


def test_oversized_save_is_rejected_before_mutation(client: ExampleClient) -> None:
    token, cookie = _csrf(client)
    body = json.dumps({"name": "A" * 4096, "pinned": False}).encode("ascii")
    response = _post(client, body, token=token, cookie=cookie)
    assert response.status_code == 413
    assert 'data-project-name="Pyganini island"' in client.get("/").text
