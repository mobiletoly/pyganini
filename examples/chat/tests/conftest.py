"""Shared Chat example fixtures."""

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from app.main import create_app

from .client import ExampleClient, as_example_client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def client() -> Iterator[ExampleClient]:
    """Yield a fresh zero-delay application client."""
    with TestClient(create_app(send_delay=0, heartbeat_seconds=0.01)) as test_client:
        yield as_example_client(test_client)
