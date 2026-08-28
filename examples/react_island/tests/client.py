"""Typed facade for the pinned Starlette test client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

import httpx2
from starlette.testclient import TestClient


class ExampleClient(Protocol):
    def get(self, url: str) -> httpx2.Response: ...

    def post(
        self,
        url: str,
        *,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx2.Response: ...


def as_example_client(client: TestClient) -> ExampleClient:
    return cast(ExampleClient, client)
