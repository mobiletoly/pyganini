"""Strict consumer checks for the public CSRF helper signatures."""

from __future__ import annotations

from pathlib import Path

import pytest
from typing_contract_support import assert_checker_result, run_checker

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
_EXPECTED_DIAGNOSTICS = {
    "mypy": (
        (":6:", 'Argument "secret" to "Guard"', 'expected "bytes"', "[arg-type]"),
        (":7:", 'Argument "max_age" to "Guard"', 'expected "int"', "[arg-type]"),
        (
            ":8:",
            'Argument "same_site" to "Guard"',
            "Literal[1]",
            "Literal['lax', 'strict', 'none']",
            "[arg-type]",
        ),
        (
            ":11:",
            'Argument 1 to "validate" of "Guard"',
            'expected "Request[State]"',
            "[arg-type]",
        ),
        (
            ":11:",
            'Argument 2 to "validate" of "Guard"',
            'expected "str"',
            "[arg-type]",
        ),
    ),
    "pyright": (
        (
            ":6:",
            'parameter "secret"',
            'type "bytes"',
            'function "__init__"',
            "reportArgumentType",
        ),
        (
            ":7:",
            'parameter "max_age"',
            'type "int"',
            'function "__init__"',
            "reportArgumentType",
        ),
        (
            ":8:",
            'parameter "same_site"',
            "Literal[1]",
            "Literal['lax', 'strict', 'none']",
            'function "__init__"',
            "reportArgumentType",
        ),
        (
            ":11:",
            'parameter "request"',
            'type "Request[State]"',
            'function "validate"',
            "reportArgumentType",
        ),
        (
            ":11:",
            'parameter "form_token"',
            'type "str"',
            'function "validate"',
            "reportArgumentType",
        ),
    ),
}


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize(
    ("fixture", "accepted"),
    [("csrf_consumer_valid.py", True), ("csrf_consumer_invalid.py", False)],
)
def test_csrf_consumer_contract_is_checked_by_both_type_checkers(
    checker: str, fixture: str, accepted: bool
) -> None:
    result = run_checker(checker, FIXTURES / fixture, root=ROOT)
    assert_checker_result(
        result,
        checker=checker,
        accepted=accepted,
        expected_diagnostics=_EXPECTED_DIAGNOSTICS,
    )
