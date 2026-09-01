import tarfile
import zipfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from conftest import PackageBuild

PACKAGE_FILES = {
    "pyganini/__init__.py",
    "pyganini/__main__.py",
    "pyganini/_assets.py",
    "pyganini/_cli.py",
    "pyganini/_config.py",
    "pyganini/_declarations.py",
    "pyganini/_dispatch.py",
    "pyganini/_dispatch_generation.py",
    "pyganini/_filesystem.py",
    "pyganini/_generation.py",
    "pyganini/_inspection.py",
    "pyganini/_navigation.py",
    "pyganini/hx.py",
    "pyganini/_paths.py",
    "pyganini/_render.py",
    "pyganini/_route_graph.py",
    "pyganini/_template_references.py",
    "pyganini/_url_binding.py",
    "pyganini/_url_generation.py",
    "pyganini/browser/__init__.py",
    "pyganini/browser/pyganini-sse-event.js",
    "pyganini/browser/pyganini-template-inspector.js",
    "pyganini/csrf.py",
    "pyganini/py.typed",
    "pyganini/request_data.py",
    "pyganini/sse.py",
}


def _wheel_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def _metadata(path: Path) -> Message:
    with zipfile.ZipFile(path) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        return BytesParser().parsebytes(archive.read(metadata_name))


def _package_contract(path: Path) -> tuple[set[str], tuple[str, ...]]:
    names = _wheel_names(path)
    package = {name for name in names if name.startswith("pyganini/")}
    metadata = _metadata(path)
    requirements = tuple(metadata.get_all("Requires-Dist", []))
    return package, requirements


def test_wheel_metadata_entry_point_and_contents(package_build: PackageBuild) -> None:
    wheel = package_build.wheel
    assert wheel.name == "pyganini-0.1.1-py3-none-any.whl"
    names = _wheel_names(wheel)
    assert {
        name
        for name in names
        if name.startswith("pyganini/") and not name.endswith("/")
    } == PACKAGE_FILES
    assert all(
        name.startswith(("pyganini/", "pyganini-0.1.1.dist-info/")) for name in names
    )
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
    assert any(name.endswith(".dist-info/entry_points.txt") for name in names)
    assert not any(
        forbidden in name
        for name in names
        for forbidden in (
            "tests/",
            "probes/",
            "docs/",
            "examples/",
            "uv.lock",
            "__pycache__",
            ".pyc",
            "_pyganini/",
        )
    )

    metadata = _metadata(wheel)
    assert metadata["Name"] == "pyganini"
    assert metadata["Version"] == "0.1.1"
    assert metadata["Requires-Python"] == ">=3.13"
    assert metadata["License-Expression"] == "Apache-2.0"
    classifiers = metadata.get_all("Classifier") or []
    assert "Development Status :: 3 - Alpha" in classifiers
    assert not any(value.startswith("License ::") for value in classifiers)
    assert metadata.get_all("Project-URL") == [
        "Homepage, https://github.com/mobiletoly/pyganini",
        "Repository, https://github.com/mobiletoly/pyganini",
        "Issues, https://github.com/mobiletoly/pyganini/issues",
        "Documentation, https://github.com/mobiletoly/pyganini/tree/main/docs/user",
    ]
    assert metadata.get_all("Requires-Dist") == [
        "anyio>=4.14.2,<4.15",
        "jinja2>=3.1.6,<4",
        "python-multipart>=0.0.32,<0.0.33",
        "starlette>=1.6.0,<1.7",
    ]
    assert metadata["Description-Content-Type"] == "text/markdown"

    with zipfile.ZipFile(wheel) as archive:
        entry_points_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/entry_points.txt")
        )
        assert archive.read(entry_points_name).decode("ascii").strip() == (
            "[console_scripts]\npyganini = pyganini._cli:main"
        )


def test_source_distribution_has_exact_project_boundary(
    package_build: PackageBuild,
) -> None:
    with tarfile.open(package_build.sdist, "r:gz") as archive:
        names = set(archive.getnames())
    root = "pyganini-0.1.1/"
    assert {
        name
        for name in names
        if name.startswith(f"{root}src/pyganini/") and not name.endswith("/")
    } == {
        f"{root}src/pyganini/browser",
        *(f"{root}src/{name}" for name in PACKAGE_FILES),
    }
    assert {
        f"{root}LICENSE",
        f"{root}README.md",
        f"{root}pyproject.toml",
        *(f"{root}src/{name}" for name in PACKAGE_FILES),
    } <= names
    assert not any(
        name.startswith(
            (
                f"{root}tests/",
                f"{root}probes/",
                f"{root}docs/",
                f"{root}examples/",
                f"{root}.venv/",
                f"{root}build/",
                f"{root}dist/",
            )
        )
        or name == f"{root}uv.lock"
        or "__pycache__" in name
        or name.endswith((".pyc", ".pyo"))
        for name in names
    )


def test_wheel_rebuilt_from_sdist_has_same_contract(
    package_build: PackageBuild,
) -> None:
    assert _package_contract(package_build.sdist_wheel) == _package_contract(
        package_build.wheel
    )
