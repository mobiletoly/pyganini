"""Public content values and source callables remain explicit and typed."""

from pathlib import Path

import pytest
from typing_contract_support import assert_checker_result, run_checker

ROOT = Path(__file__).resolve().parents[1]
_EXPECTED = {
    "mypy": (
        ('Argument 1 to "AdditionalPage"', "[arg-type]"),
        ('Argument "root" to "Config"', "[arg-type]"),
        ('Argument 1 to "check"', "[arg-type]"),
        ("Incompatible types in assignment", "[assignment]"),
    ),
    "pyright": (
        ('parameter "body"', "reportArgumentType"),
        ('parameter "root"', "reportArgumentType"),
        ('function "check"', "reportArgumentType"),
        ("AdditionalPageSource", "reportAssignmentType"),
    ),
}


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize("accepted", [True, False])
def test_content_consumer_contract(checker: str, accepted: bool) -> None:
    sample = (
        ROOT
        / "tests/fixtures"
        / ("content_consumer_valid.py" if accepted else "content_consumer_invalid.py")
    )
    result = run_checker(checker, sample, root=ROOT)
    assert_checker_result(
        result, checker=checker, accepted=accepted, expected_diagnostics=_EXPECTED
    )
