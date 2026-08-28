"""Strict consumer checks for the public SSE helper signatures."""

from __future__ import annotations

from pathlib import Path

import pytest
from typing_contract_support import assert_checker_result, run_checker

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
_EXPECTED_DIAGNOSTICS = {
    "mypy": (
        (":5:", 'Argument "data" to "Event"', 'expected "str"', "[arg-type]"),
        (":6:", 'Argument "id" to "Event"', 'expected "str | None"', "[arg-type]"),
        (":7:", 'Argument "name" to "Event"', 'expected "str | None"', "[arg-type]"),
        (":8:", 'Argument "retry" to "Event"', 'expected "int | None"', "[arg-type]"),
        (":9:", 'Too many positional arguments for "Event"', "[call-arg]"),
        (":10:", 'Argument 1 to "encode_event"', 'expected "Event"', "[arg-type]"),
        (":11:", 'Argument 1 to "encode_comment"', 'expected "str"', "[arg-type]"),
        (
            ":12:",
            'Argument 1 to "last_event_id"',
            'expected "Request[State]"',
            "[arg-type]",
        ),
    ),
    "pyright": (
        (
            ":5:",
            'parameter "data"',
            'type "str"',
            'function "__init__"',
            "reportArgumentType",
        ),
        (
            ":6:",
            'parameter "id"',
            'type "str | None"',
            'function "__init__"',
            "reportArgumentType",
        ),
        (
            ":7:",
            'parameter "name"',
            'type "str | None"',
            'function "__init__"',
            "reportArgumentType",
        ),
        (
            ":8:",
            'parameter "retry"',
            'type "int | None"',
            'function "__init__"',
            "reportArgumentType",
        ),
        (":9:", "Expected 0 positional arguments", "reportCallIssue"),
        (
            ":10:",
            'parameter "event"',
            'type "Event"',
            'function "encode_event"',
            "reportArgumentType",
        ),
        (
            ":11:",
            'parameter "comment"',
            'type "str"',
            'function "encode_comment"',
            "reportArgumentType",
        ),
        (
            ":12:",
            'parameter "request"',
            'type "Request[State]"',
            'function "last_event_id"',
            "reportArgumentType",
        ),
    ),
}


@pytest.mark.parametrize("checker", ["mypy", "pyright"])
@pytest.mark.parametrize(
    ("fixture", "accepted"),
    [("sse_consumer_valid.py", True), ("sse_consumer_invalid.py", False)],
)
def test_sse_consumer_contract_is_checked_by_both_type_checkers(
    checker: str, fixture: str, accepted: bool
) -> None:
    result = run_checker(checker, FIXTURES / fixture, root=ROOT)
    assert_checker_result(
        result,
        checker=checker,
        accepted=accepted,
        expected_diagnostics=_EXPECTED_DIAGNOSTICS,
    )
