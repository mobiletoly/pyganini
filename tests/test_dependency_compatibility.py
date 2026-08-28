import tomllib
from importlib.metadata import requires, version
from pathlib import Path
from typing import Any


def test_exact_locked_host_stack_is_importable() -> None:
    assert version("starlette") == "1.6.0"
    assert version("fastapi") == "0.141.1"
    assert version("jinja2") == "3.1.6"
    assert version("anyio") == "4.14.2"
    assert version("python-multipart") == "0.0.32"
    assert version("httpx") == "0.28.1"
    assert version("httpx2") == "2.12.0"


def test_declared_dependency_overlap_has_no_override() -> None:
    fastapi_requirements = requires("fastapi") or []
    pyganini_requirements = requires("pyganini") or []
    assert any(
        requirement.startswith("starlette>=0.46.0")
        for requirement in fastapi_requirements
    )
    assert pyganini_requirements == [
        "anyio>=4.14.2,<4.15",
        "jinja2>=3.1.6,<4",
        "python-multipart>=0.0.32,<0.0.33",
        "starlette>=1.6.0,<1.7",
    ]

    with Path("pyproject.toml").open("rb") as source:
        project: dict[str, Any] = tomllib.load(source)
    uv = project.get("tool", {}).get("uv", {})
    assert "override-dependencies" not in uv
    assert "constraint-dependencies" not in uv
    assert "sources" not in uv
