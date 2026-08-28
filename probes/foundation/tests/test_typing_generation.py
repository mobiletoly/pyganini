import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from foundation_probes.typing_generation import (
    candidate,
    generate_runtime,
    generate_stub,
    write_candidate,
)

SAMPLES = Path(__file__).parent / "typing_samples"


def _run(
    module: str, sample: Path, directory: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, str(sample.name)],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )


def _line_for(marker: str) -> int:
    lines = (SAMPLES / "expected_failures.py").read_text(encoding="ascii").splitlines()
    return next(index for index, line in enumerate(lines, 1) if marker in line)


def _prepare(directory: Path, kind: str) -> tuple[Path, Path]:
    write_candidate(directory, kind)
    valid = directory / "valid_usage.py"
    invalid = directory / "expected_failures.py"
    valid.write_bytes((SAMPLES / valid.name).read_bytes())
    invalid.write_bytes((SAMPLES / invalid.name).read_bytes())
    return valid, invalid


@pytest.mark.parametrize("kind", ["py", "pyi"])
@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_generated_candidates_pass_valid_and_reject_invalid_usage(
    tmp_path: Path,
    kind: str,
    checker: str,
) -> None:
    directory = tmp_path / kind / checker
    valid, invalid = _prepare(directory, kind)
    valid_result = _run(checker, valid, directory)
    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr

    invalid_result = _run(checker, invalid, directory)
    output = invalid_result.stdout + invalid_result.stderr
    assert invalid_result.returncode != 0
    assert f":{_line_for('MISSING_PARAMETER')}:" in output
    assert f":{_line_for('UNKNOWN_PARAMETER')}:" in output
    assert f":{_line_for('WRONG_PARAMETER_TYPE')}:" in output
    lowered = output.lower()
    if checker == "mypy":
        assert "missing positional argument" in lowered
        assert "unexpected keyword argument" in lowered
        assert "incompatible type" in lowered
    else:
        assert "argument missing" in lowered
        assert "no parameter named" in lowered
        assert "cannot be assigned" in lowered


def test_generation_is_deterministic_and_checked_runtime_matches() -> None:
    assert generate_runtime() == generate_runtime()
    assert generate_stub() == generate_stub()
    assert (SAMPLES / "generated_urls.py").read_text(
        encoding="ascii"
    ) == generate_runtime()


@pytest.mark.parametrize("kind", ["py", "pyi"])
def test_runtime_import_agrees_with_checked_surface(tmp_path: Path, kind: str) -> None:
    directory = tmp_path / kind
    write_candidate(directory, kind)
    source = directory / "generated_urls.py"
    specification = importlib.util.spec_from_file_location(f"generated_{kind}", source)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    typed_module = module
    assert isinstance(typed_module, ModuleType)
    assert typed_module.urls.home == "/"
    assert typed_module.urls.user(7).path == "/users/7"
    assert typed_module.urls.user(7).edit == "/users/7/edit"


def test_unknown_candidate_is_rejected() -> None:
    with pytest.raises(ValueError, match="typing-generation phase"):
        candidate("unknown")
