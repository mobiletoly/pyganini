"""Small typed facade for the pinned Starlette test client surface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

import httpx2
from starlette.testclient import TestClient


class ExampleClient(Protocol):
    """The typed HTTP methods used by the example's tests."""

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
        files: object = None,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response: ...


def as_example_client(client: TestClient) -> ExampleClient:
    """Expose only the typed methods used by application tests."""
    return cast(ExampleClient, client)
