from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def _run(
    command: list[str], *, cwd: Path, environment: dict[str, str] | None = None
) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"command failed: {command!r}\n"
            f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
        )


@pytest.fixture
def git_repository(tmp_path: Path) -> Callable[[], Path]:
    def create() -> Path:
        root = tmp_path / "candidate"
        root.mkdir()
        _run(["git", "init", "-b", "main"], cwd=root)
        _run(["git", "config", "user.name", "Qualification Test"], cwd=root)
        _run(["git", "config", "user.email", "qualification@invalid"], cwd=root)
        (root / ".gitignore").write_text("ignored/\n", encoding="ascii")
        (root / "pyproject.toml").write_text("[tool.pyganini]\n", encoding="ascii")
        (root / "tracked.txt").write_bytes(b"tracked\n")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
            }
        )
        _run(["git", "add", "--all"], cwd=root)
        _run(["git", "commit", "-m", "baseline"], cwd=root, environment=environment)
        return root

    return create
