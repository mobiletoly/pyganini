"""Focused tests for the optional SSE wire helpers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from inspect import Parameter, signature

import pytest
from starlette.requests import Request

from pyganini import sse


def _request(*headers: tuple[bytes, bytes]) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/events",
        "raw_path": b"/events",
        "query_string": b"",
        "headers": list(headers),
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_public_surface_and_event_shape() -> None:
    assert sse.__all__ == [
        "HEADER_LAST_EVENT_ID",
        "MEDIA_TYPE",
        "Event",
        "encode_comment",
        "encode_event",
        "last_event_id",
    ]
    assert sse.MEDIA_TYPE == "text/event-stream"
    assert sse.HEADER_LAST_EVENT_ID == "Last-Event-ID"
    assert is_dataclass(sse.Event)
    assert sse.Event.__slots__ == ("data", "id", "name", "retry")
    assert tuple(field.name for field in fields(sse.Event)) == (
        "data",
        "id",
        "name",
        "retry",
    )
    parameters = tuple(signature(sse.Event).parameters.values())
    assert all(parameter.kind is Parameter.KEYWORD_ONLY for parameter in parameters)

    event = sse.Event(data="payload")
    with pytest.raises(FrozenInstanceError):
        event.data = "changed"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("data", 1, "data must be a str"),
        ("id", 1, "id must be a str or None"),
        ("name", 1, "name must be a str or None"),
        ("retry", "2000", "retry must be an int or None"),
        ("retry", True, "retry must be an int or None"),
    ],
)
def test_event_rejects_wrong_types(field: str, value: object, message: str) -> None:
    with pytest.raises(TypeError, match=f"^{message}$"):
        sse.Event(**{field: value})


@pytest.mark.parametrize("value", ["1\x002", "1\r2", "1\n2"])
def test_event_rejects_unsafe_ids(value: str) -> None:
    with pytest.raises(ValueError, match=r"^id must not contain NULL, CR, or LF$"):
        sse.Event(id=value)


@pytest.mark.parametrize("value", ["contact\rname", "contact\nname"])
def test_event_rejects_unsafe_names(value: str) -> None:
    with pytest.raises(ValueError, match=r"^name must not contain CR or LF$"):
        sse.Event(name=value)


def test_event_rejects_negative_retry() -> None:
    with pytest.raises(ValueError, match=r"^retry must be zero or greater$"):
        sse.Event(retry=-1)


def test_event_encoding_is_deterministic_and_ordered() -> None:
    event = sse.Event(
        id="42",
        name="contact",
        retry=2_000,
        data="Ada\r\nLovelace",
    )

    assert sse.encode_event(event) == (
        b"id: 42\nevent: contact\nretry: 2000\ndata: Ada\ndata: Lovelace\n\n"
    )


def test_event_encoding_preserves_empty_logical_lines() -> None:
    event = sse.Event(data="\rA\n\nB\r\n")

    assert sse.encode_event(event) == (b"data: \ndata: A\ndata: \ndata: B\ndata: \n\n")


def test_event_encoding_omits_none_and_keeps_explicit_empty_values() -> None:
    assert sse.encode_event(sse.Event()) == b"data: \n\n"
    assert sse.encode_event(sse.Event(id="", name="", retry=0, data="x")) == (
        b"id: \nevent: \nretry: 0\ndata: x\n\n"
    )


def test_event_encoding_returns_utf8_bytes() -> None:
    event = sse.Event(data="cafe\N{LATIN SMALL LETTER E WITH ACUTE}")

    assert sse.encode_event(event) == (
        "data: cafe\N{LATIN SMALL LETTER E WITH ACUTE}\n\n".encode("utf-8")
    )


def test_event_encoding_preserves_utf8_encoding_failure() -> None:
    with pytest.raises(UnicodeEncodeError):
        sse.encode_event(sse.Event(data="bad\ud800"))


def test_encode_event_rejects_wrong_type() -> None:
    with pytest.raises(TypeError, match=r"^event must be an sse\.Event$"):
        sse.encode_event(object())


def test_comment_encoding_is_deterministic_and_preserves_empty_lines() -> None:
    assert sse.encode_comment("connected\r\nagain") == b": connected\n: again\n\n"
    assert sse.encode_comment("\rA\n\nB\r\n") == b": \n: A\n: \n: B\n: \n\n"
    assert sse.encode_comment("") == b": \n\n"


def test_comment_encoding_returns_utf8_bytes() -> None:
    assert sse.encode_comment("cafe\N{LATIN SMALL LETTER E WITH ACUTE}") == (
        ": cafe\N{LATIN SMALL LETTER E WITH ACUTE}\n\n".encode("utf-8")
    )


def test_comment_encoding_preserves_utf8_encoding_failure() -> None:
    with pytest.raises(UnicodeEncodeError):
        sse.encode_comment("bad\ud800")


def test_encode_comment_rejects_wrong_type() -> None:
    with pytest.raises(TypeError, match=r"^comment must be a str$"):
        sse.encode_comment(object())


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ([(b"last-event-id", b"42")], "42"),
        ([(b"last-event-id", b" 42 : visible ")], " 42 : visible "),
        ([(b"LAST-EVENT-ID", b"")], ""),
        ([], ""),
    ],
)
def test_last_event_id_reads_starlette_headers(
    headers: list[tuple[bytes, bytes]], expected: str
) -> None:
    assert sse.last_event_id(_request(*headers)) == expected


def test_last_event_id_rejects_wrong_type() -> None:
    with pytest.raises(
        TypeError,
        match=r"^request must be a starlette\.requests\.Request$",
    ):
        sse.last_event_id(object())
