from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from qualification_probes.scenarios import (
    SCENARIOS,
    ScenarioContext,
    ScenarioError,
    select_scenarios,
    validate_registry,
)


def test_registry_has_stable_table_order_and_unique_ids() -> None:
    validate_registry(SCENARIOS)
    assert [scenario.id for scenario in SCENARIOS] == [
        "Q001",
        "Q010",
        "Q011",
        "Q020",
        "Q030",
        "Q031",
        "Q040",
        "Q041",
        "Q042",
        "Q043",
        "Q044",
        "Q050",
        "Q060",
        "Q070",
        "Q080",
    ]


def test_selection_adds_dependencies_in_table_order() -> None:
    selected = select_scenarios(("Q031",), SCENARIOS)
    assert [scenario.id for scenario in selected] == [
        "Q001",
        "Q020",
        "Q031",
        "Q080",
    ]


def test_worker_commands_disable_bytecode_writes(tmp_path: Path) -> None:
    context = ScenarioContext(
        python="python",
        candidate_root=tmp_path / "candidate",
        wheel=tmp_path / "pyganini.whl",
        temporary_root=tmp_path,
        probe_root=tmp_path,
        python_lines=("3.14",),
    )

    command = SCENARIOS[1].command_builder(context, "Q010")

    assert command[:3] == ("python", "-B", "-m")


def test_registry_rejects_duplicates_unknown_dependencies_and_cycles() -> None:
    first = SCENARIOS[0]
    with pytest.raises(ScenarioError, match="duplicate"):
        validate_registry((first, first))
    with pytest.raises(ScenarioError, match="unknown dependency"):
        validate_registry((replace(first, dependencies=("Q999",)),))
    cyclic_a = replace(SCENARIOS[0], dependencies=("Q010",))
    cyclic_b = replace(SCENARIOS[1], dependencies=("Q001",))
    with pytest.raises(ScenarioError, match="cycle"):
        validate_registry((cyclic_a, cyclic_b))


def test_selection_rejects_duplicates_unknown_and_empty_filters() -> None:
    with pytest.raises(ScenarioError, match="duplicate scenario filter"):
        select_scenarios(("Q001", "Q001"), SCENARIOS)
    with pytest.raises(ScenarioError, match="unknown scenario"):
        select_scenarios(("Q999",), SCENARIOS)
    with pytest.raises(ScenarioError, match="empty"):
        select_scenarios((), ())
