"""Focused self-tests for the shared typing-contract result harness."""

from __future__ import annotations

import subprocess

import pytest
from typing_contract_support import assert_checker_result

_EXPECTED = {"mypy": ((":5:", "expected detail", "[arg-type]"),)}


@pytest.mark.parametrize(
    ("output", "match"),
    [
        (
            "consumer.py:3: error: Cannot find implementation or library stub "
            'for module named "pyganini" [import-not-found]\n',
            "checker setup failure",
        ),
        (
            "consumer.py:5: error: different detail [name-defined]\n",
            "missing expected mypy diagnostic",
        ),
    ],
)
def test_rejected_result_requires_real_and_complete_contract_diagnostics(
    output: str,
    match: str,
) -> None:
    result = subprocess.CompletedProcess(["mypy"], 1, stdout=output, stderr="")

    with pytest.raises(AssertionError, match=match):
        assert_checker_result(
            result,
            checker="mypy",
            accepted=False,
            expected_diagnostics=_EXPECTED,
        )

    complete = subprocess.CompletedProcess(
        ["mypy"],
        1,
        stdout="consumer.py:5: error: expected detail [arg-type]\n",
        stderr="",
    )
    assert_checker_result(
        complete,
        checker="mypy",
        accepted=False,
        expected_diagnostics=_EXPECTED,
    )
