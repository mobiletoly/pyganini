from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount
from starlette.testclient import TestClient

from app import development
from app.main import create_app, create_development_app


def test_reload_is_explicit_development_only_and_prefix_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = tmp_path / "revision"
    revision.write_text("session:0")
    monkeypatch.setenv("PYGANINI_EXAMPLE_RELOAD_FILE", str(revision))
    with TestClient(Starlette(routes=[Mount("/demo", app=create_app())])) as client:
        assert client.get("/demo/_example/reload").status_code == 404
        assert "data-events-url=" not in client.get("/demo/privacy").text
    host = Starlette(routes=[Mount("/demo", app=create_development_app())])
    with TestClient(host) as client:
        page = client.get("/demo/privacy")
        assert 'data-events-url="/demo/_example/reload"' in page.text
        assert 'src="/demo/assets/dev-reload.' in page.text


class _Connection(Request):
    disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def test_revision_stream_offloads_reads_emits_changes_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "revision"
    path.write_text("session:0")
    threads: list[int] = []
    original = Path.read_text

    def read(self: Path, *args: object, **kwargs: object) -> str:
        threads.append(threading.get_ident())
        return original(self, encoding="ascii")

    monkeypatch.setattr(Path, "read_text", read)

    async def proof() -> None:
        request = _Connection({"type": "http"})
        stream = development.revisions(request, path)
        assert await anext(stream) == b"event: reload\ndata: session:0\n\n"
        path.write_text("session:1")
        assert await anext(stream) == b"event: reload\ndata: session:1\n\n"
        request.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(proof())
    assert len(threads) == 2
    assert all(thread != threading.get_ident() for thread in threads)


def test_missing_coordination_ends_stream_with_application_logging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def proof() -> None:
        for path in [None, tmp_path / "missing"]:
            stream = development.revisions(_Connection({"type": "http"}), path)
            with pytest.raises(StopAsyncIteration):
                await anext(stream)

    asyncio.run(proof())
    assert "revision read failed" in caplog.text
