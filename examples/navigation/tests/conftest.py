from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from app.main import create_app

from .client import ExampleClient, as_example_client


@pytest.fixture
def client() -> Iterator[ExampleClient]:
    with TestClient(create_app()) as test_client:
        yield as_example_client(test_client)
