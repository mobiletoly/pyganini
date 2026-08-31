"""Typed facade for the Starlette test client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

import httpx2
from starlette.testclient import TestClient


class ExampleClient(Protocol):
    """HTTP methods used by the Chat example tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response: ...

    def post(
        self,
        url: str,
        *,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response: ...


def as_example_client(client: TestClient) -> ExampleClient:
    """Expose the typed HTTP methods used by tests."""
    return cast(ExampleClient, client)
