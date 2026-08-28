"""Tests for the optional signed-cookie CSRF helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping, Sequence
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any

import pytest
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route, Router
from starlette.testclient import TestClient
from starlette.types import Message, Scope

from pyganini import csrf

FIXED_TIME = int(time.time())
SECRET = b"0123456789abcdef0123456789abcdef"


def _scope(
    method: str = "GET",
    *,
    cookie: str = "",
    headers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    scope_type: str = "http",
) -> Scope:
    header_items = headers.items() if isinstance(headers, Mapping) else headers or ()
    raw_headers = [
        (name.lower().encode("ascii"), value.encode("ascii"))
        for name, value in header_items
    ]
    if cookie:
        raw_headers.append((b"cookie", cookie.encode("latin-1")))
    return {
        "type": scope_type,
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }


def _request(
    method: str = "POST",
    *,
    cookie: str = "",
    headers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> Request:
    return Request(_scope(method, cookie=cookie, headers=headers))


def _signed_token(
    guard: csrf.Guard,
    issued_at: int,
    *,
    nonce: bytes = bytes(range(32)),
) -> str:
    encoded_nonce = base64.urlsafe_b64encode(nonce).rstrip(b"=").decode("ascii")
    payload = f"v1.{issued_at}.{encoded_nonce}"
    signature = hmac.new(
        guard._secret, payload.encode("ascii"), hashlib.sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{payload}.{encoded_signature}"


def _cookie_value(messages: list[Message], name: str = csrf.DEFAULT_COOKIE_NAME) -> str:
    for message in messages:
        if message["type"] != "http.response.start":
            continue
        for header, value in message["headers"]:
            if header.lower() != b"set-cookie":
                continue
            cookies = SimpleCookie()
            cookies.load(value.decode("latin-1"))
            if name in cookies:
                return cookies[name].value
    raise AssertionError(f"cookie {name!r} was not emitted")


@pytest.mark.parametrize(
    ("argument", "value", "error", "message"),
    [
        ("secret", "wrong", TypeError, "secret must be bytes"),
        ("secret", b"short", ValueError, "secret must contain at least 32 bytes"),
        ("cookie_name", 1, TypeError, "cookie_name must be a string"),
        (
            "cookie_name",
            "",
            ValueError,
            "cookie_name must be a non-empty ASCII token",
        ),
        (
            "cookie_name",
            "bad name",
            ValueError,
            "cookie_name must contain only RFC token characters",
        ),
        (
            "cookie_name",
            "\u0442\u043e\u043a\u0435\u043d",
            ValueError,
            "cookie_name must be a non-empty ASCII token",
        ),
        ("cookie_path", 1, TypeError, "cookie_path must be a string"),
        ("cookie_path", "", ValueError, "cookie_path must be an ASCII path"),
        ("cookie_path", "app", ValueError, "cookie_path must be an ASCII path"),
        ("cookie_path", "/app;bad", ValueError, "cookie_path must be an ASCII path"),
        ("cookie_path", "/app\x00", ValueError, "cookie_path must be an ASCII path"),
        ("max_age", True, TypeError, "max_age must be an integer"),
        ("max_age", "12", TypeError, "max_age must be an integer"),
        ("max_age", 0, ValueError, "max_age must be at least one second"),
        (
            "max_age",
            10**100,
            ValueError,
            "max_age must be at most 2147483647 seconds",
        ),
        ("secure", "yes", TypeError, "secure must be a bool"),
        ("same_site", 1, TypeError, "same_site must be a string"),
        ("same_site", "invalid", ValueError, "same_site must be 'lax'"),
        (
            "same_site",
            "none",
            ValueError,
            "same_site='none' requires secure=True",
        ),
    ],
)
def test_guard_rejects_invalid_configuration(
    argument: str, value: object, error: type[Exception], message: str
) -> None:
    kwargs: dict[str, Any] = {}
    secret: object = SECRET
    if argument == "secret":
        secret = value
    else:
        kwargs[argument] = value
    with pytest.raises(error, match=message):
        csrf.Guard(secret=secret, **kwargs)  # type: ignore[arg-type]


def test_guard_applies_defaults_and_copies_secret() -> None:
    guard = csrf.Guard(secret=SECRET)
    assert guard._secret == SECRET
    assert type(guard._secret) is bytes
    assert guard._cookie_name == csrf.DEFAULT_COOKIE_NAME
    assert guard._cookie_path == "/"
    assert guard._max_age == 43_200
    assert guard._secure is False
    assert guard._same_site == "lax"


def test_guard_max_age_is_not_racy_with_later_cookie_issuance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    guard = csrf.Guard(secret=SECRET, max_age=2_147_483_647)

    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME + 1)
    value, issued_at = guard._issue_token()

    assert issued_at == FIXED_TIME + 1
    assert guard._cookie_header(value, issued_at).startswith(b"pyganini_csrf=")


def test_token_wire_format_is_versioned_and_fixed_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    monkeypatch.setattr(csrf.secrets, "token_bytes", lambda size: b"n" * size)

    value, issued_at = guard._issue_token()
    parts = value.split(".")

    assert issued_at == FIXED_TIME
    assert parts[0] == "v1"
    assert parts[1] == str(FIXED_TIME)
    assert len(parts) == 4
    assert len(parts[2]) == 43
    assert len(parts[3]) == 43
    assert "=" not in value
    assert "+" not in value
    assert "/" not in value
    guard._validate_token(value, FIXED_TIME)


@pytest.mark.parametrize(
    "value",
    [
        "v2.1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "v1.+.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "v1.1.AA=.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "v1.1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.extra.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "v1.1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "v1.-1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        f"v1.1.{'A' * 42}.{'A' * 43}",
        f"v1.1.{'A' * 42} .{'A' * 43}",
        f"v1.1.{'A' * 42}+.{'A' * 43}",
        f"v1.1.{'A' * 42}/.{'A' * 43}",
        f"v1.1.{'A' * 42}\N{LATIN SMALL LETTER E WITH ACUTE}.{'A' * 43}",
    ],
)
def test_malformed_token_wire_values_are_rejected(value: str) -> None:
    guard = csrf.Guard(secret=SECRET)
    request = _request(cookie=f"{csrf.DEFAULT_COOKIE_NAME}={value}")
    with pytest.raises(csrf.MalformedTokenError, match="malformed CSRF token"):
        guard.validate(request, value)


def test_validation_safe_methods_and_unknown_unsafe_methods() -> None:
    guard = csrf.Guard(secret=SECRET)
    for method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        guard.validate(_request(method), "")
    with pytest.raises(csrf.MissingTokenError):
        guard.validate(_request("CONNECT"), "")


def test_validation_uses_header_precedence_and_case_insensitive_lookup() -> None:
    guard = csrf.Guard(secret=SECRET)
    value = _signed_token(guard, FIXED_TIME)
    cookie = f"{csrf.DEFAULT_COOKIE_NAME}={value}"

    guard.validate(_request(cookie=cookie), value)
    guard.validate(
        _request(cookie=cookie, headers={"x-csrf-token": value}),
        "wrong-form-value",
    )
    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(
            _request(cookie=cookie, headers={"X-CSRF-TOKEN": "wrong-header"}),
            value,
        )


@pytest.mark.parametrize(
    "headers",
    [
        [("X-CSRF-Token", ""), ("x-csrf-token", "wrong-header")],
        [("X-CSRF-Token", "wrong-header"), ("x-csrf-token", "")],
        [("X-CSRF-Token", "valid"), ("x-csrf-token", "valid")],
    ],
)
def test_validation_rejects_duplicate_token_headers_without_order_selection(
    headers: list[tuple[str, str]],
) -> None:
    guard = csrf.Guard(secret=SECRET)
    value = _signed_token(guard, FIXED_TIME)
    normalized = [
        (name, value if header_value == "valid" else header_value)
        for name, header_value in headers
    ]
    request = _request(
        cookie=f"{csrf.DEFAULT_COOKIE_NAME}={value}",
        headers=normalized,
    )

    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(request, value)


@pytest.mark.parametrize(
    "cookie_values",
    [
        ("valid", "wrong-cookie"),
        ("wrong-cookie", "valid"),
        ("valid", "valid"),
    ],
)
def test_validation_rejects_duplicate_cookies_without_order_selection(
    cookie_values: tuple[str, str],
) -> None:
    guard = csrf.Guard(secret=SECRET)
    value = _signed_token(guard, FIXED_TIME)
    cookie = "; ".join(
        f"{csrf.DEFAULT_COOKIE_NAME}={value if item == 'valid' else item}"
        for item in cookie_values
    )

    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(_request(cookie=cookie), value)


@pytest.mark.parametrize(
    ("cookie", "submitted", "error", "message"),
    [
        ("", "", csrf.MissingTokenError, "missing CSRF token"),
        ("", "submitted", csrf.MissingCookieError, "missing CSRF cookie"),
        ("other", "submitted", csrf.BadTokenError, "bad CSRF token"),
        ("malformed", "malformed", csrf.MalformedTokenError, "malformed CSRF token"),
    ],
)
def test_validation_maps_stable_typed_errors(
    cookie: str,
    submitted: str,
    error: type[Exception],
    message: str,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    cookie_value = cookie
    if cookie == "other":
        cookie_value = _signed_token(guard, FIXED_TIME)
    with pytest.raises(error, match=message):
        guard.validate(
            _request(cookie=f"{csrf.DEFAULT_COOKIE_NAME}={cookie_value}"),
            submitted if submitted != "submitted" else "submitted",
        )


def test_validation_distinguishes_bad_signature_expiry_and_future_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET, max_age=100)
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    valid = _signed_token(guard, FIXED_TIME)
    bad_signature = _signed_token(
        csrf.Guard(secret=b"fedcba9876543210fedcba9876543210"), FIXED_TIME
    )
    expired = _signed_token(guard, FIXED_TIME - 101)
    exact_max_age = _signed_token(guard, FIXED_TIME - 100)
    future = _signed_token(guard, FIXED_TIME + 61)
    accepted_future = _signed_token(guard, FIXED_TIME + 60)

    def monkeypatch_request(value: str) -> Request:
        return _request(cookie=f"{csrf.DEFAULT_COOKIE_NAME}={value}")

    guard.validate(monkeypatch_request(valid), valid)
    guard.validate(monkeypatch_request(exact_max_age), exact_max_age)
    guard.validate(monkeypatch_request(accepted_future), accepted_future)
    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(monkeypatch_request(bad_signature), bad_signature)
    with pytest.raises(csrf.ExpiredTokenError, match="expired CSRF token"):
        guard.validate(monkeypatch_request(expired), expired)
    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(monkeypatch_request(future), future)


def test_validation_does_not_read_the_request_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    value = _signed_token(guard, FIXED_TIME)
    request = _request(cookie=f"{csrf.DEFAULT_COOKIE_NAME}={value}")

    def fail_if_called(*_: object, **__: object) -> None:
        raise AssertionError("request body was read")

    monkeypatch.setattr(request, "body", fail_if_called)
    monkeypatch.setattr(request, "form", fail_if_called)
    monkeypatch.setattr(request, "json", fail_if_called)
    guard.validate(request, value)


def test_token_and_headers_public_boundaries() -> None:
    request = _request()
    with pytest.raises(
        csrf.TokenUnavailableError,
        match="CSRF token middleware did not provide a request token",
    ):
        csrf.token(request)

    request.scope["_pyganini_csrf_token"] = "provided"
    assert csrf.token(request) == "provided"
    assert csrf.headers('tok"en') == '{"X-CSRF-Token":"tok\\"en"}'
    assert json.loads(csrf.headers("token")) == {"X-CSRF-Token": "token"}
    assert set(csrf.__all__) == {
        "FIELD_NAME",
        "HEADER_NAME",
        "META_NAME",
        "DEFAULT_COOKIE_NAME",
        "ValidationError",
        "MissingTokenError",
        "MissingCookieError",
        "MalformedTokenError",
        "BadTokenError",
        "ExpiredTokenError",
        "TokenUnavailableError",
        "Guard",
        "TokenMiddleware",
        "token",
        "headers",
    }


async def _run_middleware(
    middleware: csrf.TokenMiddleware,
    scope: Scope,
    *,
    downstream: Any | None = None,
) -> tuple[list[Message], list[Scope]]:
    messages: list[Message] = []
    scopes: list[Scope] = []

    async def default_downstream(child_scope: Scope, receive: Any, send: Any) -> None:
        scopes.append(child_scope)
        await send(
            {
                "type": "http.response.start",
                "status": 201,
                "headers": [(b"x-app", b"yes"), (b"set-cookie", b"app=1")],
            }
        )
        await send({"type": "http.response.body", "body": b"one", "more_body": True})
        await send({"type": "http.response.body", "body": b"two"})

    app = downstream or default_downstream

    async def receive() -> Message:
        raise AssertionError("middleware or downstream read the request body")

    async def send(message: Message) -> None:
        messages.append(message)

    original_app = middleware.app
    middleware.app = app
    try:
        await middleware(scope, receive, send)
    finally:
        middleware.app = original_app
    return messages, scopes


@pytest.mark.anyio
async def test_middleware_issues_cookie_and_copies_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    monkeypatch.setattr(csrf.secrets, "token_bytes", lambda size: b"n" * size)
    middleware = csrf.TokenMiddleware(lambda *_: None, guard=guard)
    original = _scope()

    messages, scopes = await _run_middleware(middleware, original)

    assert len(scopes) == 1
    assert scopes[0] is not original
    assert "_pyganini_csrf_token" not in original
    assert csrf.token(Request(scopes[0])) == _cookie_value(messages)
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 201
    assert (b"x-app", b"yes") in messages[0]["headers"]
    assert (b"set-cookie", b"app=1") in messages[0]["headers"]
    assert messages[1:] == [
        {"type": "http.response.body", "body": b"one", "more_body": True},
        {"type": "http.response.body", "body": b"two"},
    ]
    cookie_headers = [
        value
        for message in messages
        if message["type"] == "http.response.start"
        for header, value in message["headers"]
        if header.lower() == b"set-cookie"
    ]
    assert len(cookie_headers) == 2
    csrf_cookie = SimpleCookie()
    csrf_cookie.load(cookie_headers[-1].decode("latin-1"))
    morsel = csrf_cookie[csrf.DEFAULT_COOKIE_NAME]
    assert morsel["max-age"] == "43200"
    assert morsel["path"] == "/"
    assert morsel["samesite"] == "lax"
    assert "httponly" in cookie_headers[-1].decode("latin-1").lower()
    assert "secure" not in cookie_headers[-1].decode("latin-1").lower()
    cookie_text = cookie_headers[-1].decode("latin-1").lower()
    assert "; domain=" not in cookie_text
    assert "; partitioned" not in cookie_text
    assert parsedate_to_datetime(morsel["expires"]).timestamp() == FIXED_TIME + 43_200


@pytest.mark.anyio
async def test_middleware_serializes_custom_cookie_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(
        secret=SECRET,
        cookie_name="custom_csrf",
        cookie_path="/admin",
        max_age=90,
        secure=True,
        same_site="none",
    )
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    middleware = csrf.TokenMiddleware(lambda *_: None, guard=guard)

    messages, _ = await _run_middleware(middleware, _scope())

    cookie_headers = [
        value
        for message in messages
        if message["type"] == "http.response.start"
        for header, value in message["headers"]
        if header.lower() == b"set-cookie" and value.startswith(b"custom_csrf=")
    ]
    assert len(cookie_headers) == 1
    cookies = SimpleCookie()
    cookies.load(cookie_headers[0].decode("latin-1"))
    morsel = cookies["custom_csrf"]
    assert morsel["max-age"] == "90"
    assert morsel["path"] == "/admin"
    assert morsel["samesite"] == "none"
    assert parsedate_to_datetime(morsel["expires"]).timestamp() == FIXED_TIME + 90
    cookie_text = cookie_headers[0].decode("latin-1").lower()
    assert "httponly" in cookie_text
    assert "secure" in cookie_text
    assert "; domain=" not in cookie_text
    assert "; partitioned" not in cookie_text


@pytest.mark.anyio
async def test_middleware_adds_cookie_to_headerless_response_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    middleware = csrf.TokenMiddleware(lambda *_: None, guard=guard)

    async def downstream(scope: Scope, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 204})
        await send({"type": "http.response.body", "body": b""})

    messages, _ = await _run_middleware(
        middleware,
        _scope(),
        downstream=downstream,
    )

    assert messages[0]["headers"]
    assert _cookie_value(messages) != ""


@pytest.mark.anyio
async def test_middleware_reuses_valid_cookie_without_set_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    value, _ = guard._issue_token()
    middleware = csrf.TokenMiddleware(lambda *_: None, guard=guard)

    messages, scopes = await _run_middleware(
        middleware,
        _scope(cookie=f"{csrf.DEFAULT_COOKIE_NAME}={value}"),
    )

    assert csrf.token(Request(scopes[0])) == value
    assert not any(
        header.lower() == b"set-cookie" and value.startswith(b"pyganini_csrf=")
        for message in messages
        if message["type"] == "http.response.start"
        for header, value in message["headers"]
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [
        [("cookie", "pyganini_csrf=first; pyganini_csrf=second")],
        [("cookie", "pyganini_csrf=first"), ("cookie", "pyganini_csrf=second")],
    ],
)
async def test_middleware_replaces_duplicate_cookie_evidence(
    headers: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    middleware = csrf.TokenMiddleware(lambda *_: None, guard=guard)

    messages, scopes = await _run_middleware(middleware, _scope(headers=headers))

    replacement = csrf.token(Request(scopes[0]))
    assert replacement not in {"first", "second"}
    assert _cookie_value(messages) == replacement
    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(Request({**scopes[0], "method": "POST"}), replacement)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("incoming", "error"),
    [
        ("malformed", csrf.MalformedTokenError),
        ("bad-signature", csrf.BadTokenError),
        ("expired", csrf.ExpiredTokenError),
        ("future", csrf.BadTokenError),
    ],
)
async def test_middleware_replaces_each_invalid_cookie_and_validation_uses_incoming(
    incoming: str,
    error: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = csrf.Guard(secret=SECRET)
    other_guard = csrf.Guard(
        secret=b"fedcba9876543210fedcba9876543210",
    )
    monkeypatch.setattr(csrf, "_current_seconds", lambda: FIXED_TIME)
    if incoming == "malformed":
        incoming_value = "invalid"
    elif incoming == "bad-signature":
        incoming_value = _signed_token(other_guard, FIXED_TIME)
    elif incoming == "expired":
        incoming_value = _signed_token(guard, FIXED_TIME - 43_201)
    else:
        incoming_value = _signed_token(guard, FIXED_TIME + 61)
    middleware = csrf.TokenMiddleware(lambda *_: None, guard=guard)
    messages, scopes = await _run_middleware(
        middleware,
        _scope(cookie=f"{csrf.DEFAULT_COOKIE_NAME}={incoming_value}"),
    )
    replacement = csrf.token(Request(scopes[0]))
    assert replacement != incoming_value
    assert _cookie_value(messages) == replacement

    request_scope = {**scopes[0], "method": "POST"}
    request = Request(request_scope)
    with pytest.raises(error):
        guard.validate(request, incoming_value)
    with pytest.raises(csrf.BadTokenError, match="bad CSRF token"):
        guard.validate(request, replacement)


@pytest.mark.anyio
async def test_duplicate_middleware_mount_fails() -> None:
    guard = csrf.Guard(secret=SECRET)

    called = False

    async def downstream(*_: object) -> None:
        nonlocal called
        called = True

    outer = csrf.TokenMiddleware(downstream, guard=guard)
    inner = csrf.TokenMiddleware(outer, guard=guard)
    with pytest.raises(RuntimeError, match="mounted more than once"):
        await _run_middleware(inner, _scope(), downstream=outer)
    assert called is False


@pytest.mark.anyio
async def test_middleware_preserves_non_http_and_exception_identity() -> None:
    guard = csrf.Guard(secret=SECRET)
    observed: list[Scope] = []

    async def websocket_app(scope: Scope, receive: Any, send: Any) -> None:
        observed.append(scope)

    middleware = csrf.TokenMiddleware(websocket_app, guard=guard)
    scope = _scope(scope_type="websocket")
    await middleware(scope, lambda: None, lambda _: None)
    assert observed == [scope]
    assert "_pyganini_csrf_token" not in scope

    error = RuntimeError("downstream")

    async def raising_app(*_: object) -> None:
        raise error

    middleware = csrf.TokenMiddleware(raising_app, guard=guard)
    with pytest.raises(RuntimeError) as caught:
        await _run_middleware(middleware, _scope(), downstream=raising_app)
    assert caught.value is error


def test_middleware_direct_router_preserves_response_and_background_work() -> None:
    guard = csrf.Guard(secret=SECRET)
    background_calls: list[str] = []

    async def endpoint(_: Request) -> Response:
        return Response(
            "routed",
            status_code=202,
            headers={"x-router": "yes"},
            background=BackgroundTask(background_calls.append, "complete"),
        )

    router = Router(routes=[Route("/", endpoint)])
    application = csrf.TokenMiddleware(router, guard=guard)

    with TestClient(application) as client:
        response = client.get("/")

    assert response.status_code == 202
    assert response.text == "routed"
    assert response.headers["x-router"] == "yes"
    assert response.cookies[csrf.DEFAULT_COOKIE_NAME]
    assert background_calls == ["complete"]
