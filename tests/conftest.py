import os
import subprocess
import tempfile
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class PackageBuild:
    root: Path
    wheel: Path
    sdist: Path
    sdist_wheel: Path


@pytest.fixture
def make_app() -> Callable[..., Path]:
    def create(
        root: Path,
        *,
        config: str = "[tool.pyganini]\n",
        routes: bool = True,
    ) -> Path:
        root.mkdir(parents=True)
        (root / "pyproject.toml").write_text(config, encoding="ascii")
        app = root / "app"
        app.mkdir()
        (app / "__init__.py").write_text("", encoding="ascii")
        if routes:
            route_root = app / "routes"
            route_root.mkdir()
            (route_root / "__init__.py").write_text("", encoding="ascii")
        return root

    return create


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=environment, check=True)


@pytest.fixture(scope="session")
def package_build() -> Generator[PackageBuild]:
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="pyganini-package-") as temporary:
        root = Path(temporary)
        environment = os.environ.copy()
        environment["UV_CACHE_DIR"] = str(root / "uv-cache")
        direct = root / "direct"
        rebuilt = root / "from-sdist"
        _run(
            ["uv", "build", "--no-sources", "--out-dir", str(direct)],
            cwd=repository,
            environment=environment,
        )
        wheel = next(direct.glob("*.whl"))
        sdist = next(direct.glob("*.tar.gz"))
        _run(
            [
                "uv",
                "build",
                "--no-sources",
                "--wheel",
                "--out-dir",
                str(rebuilt),
                str(sdist),
            ],
            cwd=repository,
            environment=environment,
        )
        yield PackageBuild(
            root=root,
            wheel=wheel,
            sdist=sdist,
            sdist_wheel=next(rebuilt.glob("*.whl")),
        )
