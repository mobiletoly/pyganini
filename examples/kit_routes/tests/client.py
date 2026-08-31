"""Typed facade for the Starlette test client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

import httpx2
from starlette.testclient import TestClient


class ExampleClient(Protocol):
    """HTTP methods used by the example tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response: ...


def as_example_client(client: TestClient) -> ExampleClient:
    """Expose only the typed method used by tests."""
    return cast(ExampleClient, client)
