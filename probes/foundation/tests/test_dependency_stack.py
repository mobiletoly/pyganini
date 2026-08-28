from importlib.metadata import version

import anyio
import fastapi
import jinja2
import starlette


def test_exact_dependency_stack_is_importable() -> None:
    assert starlette.__version__ == "1.6.0"
    assert fastapi.__version__ == "0.139.2"
    assert jinja2.__version__ == "3.1.6"
    assert version("anyio") == "4.14.2"
    assert anyio.__name__ == "anyio"
