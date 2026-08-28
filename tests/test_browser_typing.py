"""Strict consumer checks for the public browser-helper surface."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_browser_consumer_contract_is_checked_by_both_type_checkers(
    checker: str, tmp_path: Path
) -> None:
    valid = tmp_path / "valid.py"
    valid.write_text(
        "from starlette.applications import Starlette\n"
        "from pyganini import browser\n"
        "path: str = browser.SSE_EVENT_HELPER_PATH\n"
        "inspector_path: str = browser.TEMPLATE_INSPECTOR_HELPER_PATH\n"
        "extension: str = browser.SSE_EVENT_EXTENSION_NAME\n"
        "attribute: str = browser.SSE_EVENT_ATTRIBUTE\n"
        "app: Starlette = browser.create_app()\n",
        encoding="ascii",
    )
    invalid = tmp_path / "invalid.py"
    invalid.write_text(
        "from pyganini import browser\n"
        "path: int = browser.SSE_EVENT_HELPER_PATH\n"
        "inspector_path: int = browser.TEMPLATE_INSPECTOR_HELPER_PATH\n"
        "browser.create_app(1)\n",
        encoding="ascii",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    if checker == "mypy":
        base = [sys.executable, "-m", "mypy", "--strict", "--python-version", "3.13"]
    else:
        base = [str(Path(sys.executable).parent / "pyright")]

    accepted = subprocess.run(
        [*base, str(valid)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    rejected = subprocess.run(
        [*base, str(invalid)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    output = rejected.stdout + rejected.stderr
    assert rejected.returncode != 0, output
    assert "error" in output.lower()
    assert "int" in output
    assert "positional" in output.lower() or "too many arguments" in output.lower()
