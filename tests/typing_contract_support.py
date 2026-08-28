"""Shared execution and result validation for public typing-contract tests."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

SETUP_FAILURE_MARKERS = (
    "cannot find implementation or library stub",
    "could not be resolved",
    "import-not-found",
    "reportmissingimports",
    "reportunknown",
    " is unknown",
    "no such file or directory",
    "cannot open file",
    "can't open file",
    "usage: mypy",
)


def run_checker(
    checker: str,
    sample: Path,
    *,
    root: Path,
) -> subprocess.CompletedProcess[str]:
    """Run one strict consumer fixture through mypy or Pyright."""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    command = [sys.executable, "-m", checker, str(sample)]
    if checker == "mypy":
        command.extend(["--strict", "--python-version", "3.13"])
    else:
        command = [str(Path(sys.executable).parent / "pyright"), str(sample)]
    return subprocess.run(
        command,
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def assert_checker_result(
    result: subprocess.CompletedProcess[str],
    *,
    checker: str,
    accepted: bool,
    expected_diagnostics: Mapping[str, Sequence[Sequence[str]]],
) -> None:
    """Require success or every expected rejection without setup failures."""
    output = result.stdout + result.stderr
    lowered = output.lower()
    if accepted:
        assert result.returncode == 0, output
        assert ": error:" not in lowered and " - error:" not in lowered, output
        return

    assert result.returncode != 0, output
    for marker in SETUP_FAILURE_MARKERS:
        assert marker not in lowered, f"checker setup failure ({marker}):\n{output}"
    assert "error:" in lowered, output

    blocks: list[str] = []
    current: list[str] = []
    for line in output.splitlines():
        if ": error:" in line or " - error:" in line:
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    for expected in expected_diagnostics[checker]:
        assert any(
            all(fragment in block for fragment in expected) for block in blocks
        ), f"missing expected {checker} diagnostic {tuple(expected)!r}:\n{output}"
