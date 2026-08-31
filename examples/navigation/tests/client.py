from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

import httpx2
from starlette.testclient import TestClient


class ExampleClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response: ...

    def head(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> httpx2.Response: ...


def as_example_client(client: TestClient) -> ExampleClient:
    return cast(ExampleClient, client)
