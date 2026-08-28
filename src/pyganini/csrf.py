"""Optional signed double-submit-cookie CSRF helpers."""

# pyright: reportPrivateUsage=false, reportUnnecessaryIsInstance=false

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, final

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

FIELD_NAME: Final = "csrf_token"
HEADER_NAME: Final = "X-CSRF-Token"
META_NAME: Final = "csrf-token"
DEFAULT_COOKIE_NAME: Final = "pyganini_csrf"

__all__ = [
    "DEFAULT_COOKIE_NAME",
    "FIELD_NAME",
    "HEADER_NAME",
    "META_NAME",
    "BadTokenError",
    "ExpiredTokenError",
    "Guard",
    "MalformedTokenError",
    "MissingCookieError",
    "MissingTokenError",
    "TokenMiddleware",
    "TokenUnavailableError",
    "ValidationError",
    "headers",
    "token",
]

_DEFAULT_COOKIE_PATH = "/"
_DEFAULT_MAX_AGE = 43_200
_MAX_COOKIE_MAX_AGE = 2_147_483_647
_MIN_SECRET_BYTES = 32
_TOKEN_VERSION = "v1"
_NONCE_BYTES = 32
_FUTURE_SKEW_SECONDS = 60
_COOKIE_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SCOPE_KEY = "_pyganini_csrf_token"
_COOKIE_NAME_RE = re.compile(r"[A-Za-z0-9!#$%&'*+\-.^_`|~]+\Z", re.ASCII)
_TOKEN_B64_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)


class ValidationError(Exception):
    """Base class for application-visible CSRF validation failures."""


class MissingTokenError(ValidationError):
    """The unsafe request did not submit a CSRF token."""


class MissingCookieError(ValidationError):
    """The unsafe request did not include the configured CSRF cookie."""


class MalformedTokenError(ValidationError):
    """The submitted cookie token has an invalid wire format."""


class BadTokenError(ValidationError):
    """The submitted and cookie token evidence is not valid."""


class ExpiredTokenError(ValidationError):
    """The signed CSRF token is older than the configured lifetime."""


class TokenUnavailableError(RuntimeError):
    """The token middleware did not provide a request token."""


@final
class Guard:
    """Own one application-configured signed CSRF token policy."""

    def __init__(
        self,
        *,
        secret: bytes,
        cookie_name: str = DEFAULT_COOKIE_NAME,
        cookie_path: str = _DEFAULT_COOKIE_PATH,
        max_age: int = _DEFAULT_MAX_AGE,
        secure: bool = False,
        same_site: Literal["lax", "strict", "none"] = "lax",
    ) -> None:
        if not isinstance(secret, bytes):
            raise TypeError("secret must be bytes")
        if len(secret) < _MIN_SECRET_BYTES:
            raise ValueError("secret must contain at least 32 bytes")
        if not isinstance(cookie_name, str):
            raise TypeError("cookie_name must be a string")
        if not cookie_name or not cookie_name.isascii():
            raise ValueError("cookie_name must be a non-empty ASCII token")
        if _COOKIE_NAME_RE.fullmatch(cookie_name) is None:
            raise ValueError("cookie_name must contain only RFC token characters")
        if not isinstance(cookie_path, str):
            raise TypeError("cookie_path must be a string")
        if (
            not cookie_path
            or not cookie_path.startswith("/")
            or not cookie_path.isascii()
            or ";" in cookie_path
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in cookie_path
            )
        ):
            raise ValueError(
                "cookie_path must be an ASCII path without control characters or ';'"
            )
        if isinstance(max_age, bool) or not isinstance(max_age, int):
            raise TypeError("max_age must be an integer")
        if max_age < 1:
            raise ValueError("max_age must be at least one second")
        if max_age > _MAX_COOKIE_MAX_AGE:
            raise ValueError("max_age must be at most 2147483647 seconds")
        if not isinstance(secure, bool):
            raise TypeError("secure must be a bool")
        if not isinstance(same_site, str):
            raise TypeError("same_site must be a string")
        if same_site not in {"lax", "strict", "none"}:
            raise ValueError("same_site must be 'lax', 'strict', or 'none'")
        if same_site == "none" and not secure:
            raise ValueError("same_site='none' requires secure=True")

        self._secret = bytes(secret)
        self._cookie_name = cookie_name
        self._cookie_path = cookie_path
        self._max_age = max_age
        self._secure = secure
        self._same_site: Literal["lax", "strict", "none"] = same_site

    def validate(self, request: Request, form_token: str = "") -> None:
        """Validate submitted CSRF evidence for one unsafe request."""
        if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return
        if not isinstance(form_token, str):
            raise TypeError("form_token must be a string")

        submitted_headers = request.headers.getlist(HEADER_NAME)
        if len(submitted_headers) > 1:
            raise BadTokenError("bad CSRF token")
        submitted = submitted_headers[0] if submitted_headers else ""
        if not submitted:
            submitted = form_token
        if not submitted:
            raise MissingTokenError("missing CSRF token")

        cookie_values = _cookie_values(request, self._cookie_name)
        if len(cookie_values) > 1:
            raise BadTokenError("bad CSRF token")
        cookie_token = cookie_values[0] if cookie_values else ""
        if not cookie_token:
            raise MissingCookieError("missing CSRF cookie")
        if not hmac.compare_digest(
            submitted.encode("utf-8"), cookie_token.encode("utf-8")
        ):
            raise BadTokenError("bad CSRF token")

        self._validate_token(cookie_token, _current_seconds())

    def _issue_token(self) -> tuple[str, int]:
        issued_at = _current_seconds()
        nonce = secrets.token_bytes(_NONCE_BYTES)
        payload = ".".join(
            (
                _TOKEN_VERSION,
                str(issued_at),
                _encode(nonce),
            )
        )
        signature = _sign(self._secret, payload)
        return f"{payload}.{_encode(signature)}", issued_at

    def _validate_token(self, value: str, now: int) -> None:
        payload, issued_at, signature = _parse_token(value)
        expected = _sign(self._secret, payload)
        if not hmac.compare_digest(signature, expected):
            raise BadTokenError("bad CSRF token")
        if issued_at > now + _FUTURE_SKEW_SECONDS:
            raise BadTokenError("bad CSRF token")
        if now - issued_at > self._max_age:
            raise ExpiredTokenError("expired CSRF token")

    def _cookie_header(self, value: str, issued_at: int) -> bytes:
        response = Response()
        response.set_cookie(
            self._cookie_name,
            value,
            max_age=self._max_age,
            expires=_COOKIE_EPOCH + timedelta(seconds=issued_at + self._max_age),
            path=self._cookie_path,
            secure=self._secure,
            httponly=True,
            samesite=self._same_site,
            partitioned=False,
        )
        header = response.headers.get("set-cookie")
        if header is None:
            raise RuntimeError("Starlette did not serialize the CSRF cookie")
        return header.encode("latin-1")


@final
class TokenMiddleware:
    """Make a signed request token available without rejecting requests."""

    def __init__(self, app: ASGIApp, *, guard: Guard) -> None:
        self.app = app
        self.guard = guard

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if _SCOPE_KEY in scope:
            raise RuntimeError("CSRF token middleware was mounted more than once")

        request = Request(scope, receive)
        incoming_values = _cookie_values(request, self.guard._cookie_name)
        incoming = incoming_values[0] if len(incoming_values) == 1 else ""
        issue_cookie = True
        value = ""
        if incoming:
            try:
                self.guard._validate_token(incoming, _current_seconds())
            except ValidationError:
                pass
            else:
                value = incoming
                issue_cookie = False
        if issue_cookie:
            value, issued_at = self.guard._issue_token()
            cookie_header = self.guard._cookie_header(value, issued_at)
        else:
            cookie_header = None

        scoped: Scope = dict(scope)
        scoped[_SCOPE_KEY] = value
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start" and not response_started:
                response_started = True
                if cookie_header is not None:
                    message = {
                        **message,
                        "headers": [
                            *message.get("headers", []),
                            (b"set-cookie", cookie_header),
                        ],
                    }
            await send(message)

        await self.app(scoped, receive, send_wrapper)


def token(request: Request) -> str:
    """Return the token installed by :class:`TokenMiddleware`."""
    value = request.scope.get(_SCOPE_KEY)
    if not isinstance(value, str) or not value:
        raise TokenUnavailableError(
            "CSRF token middleware did not provide a request token"
        )
    return value


def headers(token: str) -> str:
    """Return compact JSON for a visible HTMX ``hx-headers`` attribute."""
    return json.dumps({HEADER_NAME: token}, separators=(",", ":"))


def _current_seconds() -> int:
    return int(time.time())


def _cookie_values(request: Request, cookie_name: str) -> tuple[str, ...]:
    values: list[str] = []
    for header in request.headers.getlist("cookie"):
        for raw_pair in header.split(";"):
            raw_name, separator, raw_value = raw_pair.lstrip(" \t").partition("=")
            if separator and raw_name.rstrip(" \t") == cookie_name:
                values.append(raw_value)
    return tuple(values)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_fixed(value: str, length: int) -> bytes:
    if _TOKEN_B64_RE.fullmatch(value) is None:
        raise MalformedTokenError("malformed CSRF token")
    try:
        decoded = base64.b64decode(
            value.encode("ascii") + b"=", altchars=b"-_", validate=True
        )
    except (binascii.Error, UnicodeEncodeError, ValueError) as error:
        raise MalformedTokenError("malformed CSRF token") from error
    if len(decoded) != length:
        raise MalformedTokenError("malformed CSRF token")
    return decoded


def _parse_token(value: str) -> tuple[str, int, bytes]:
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != _TOKEN_VERSION:
        raise MalformedTokenError("malformed CSRF token")
    timestamp = parts[1]
    if not 1 <= len(timestamp) <= 20 or any(
        character not in "0123456789" for character in timestamp
    ):
        raise MalformedTokenError("malformed CSRF token")
    issued_at = int(timestamp)
    _decode_fixed(parts[2], _NONCE_BYTES)
    signature = _decode_fixed(parts[3], hashlib.sha256().digest_size)
    return ".".join(parts[:3]), issued_at, signature


def _sign(secret: bytes, payload: str) -> bytes:
    return hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()
