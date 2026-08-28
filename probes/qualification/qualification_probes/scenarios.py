from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ScenarioError(RuntimeError):
    """Report an invalid scenario registry or selection."""


@dataclass(frozen=True, slots=True)
class ScenarioContext:
    python: str
    candidate_root: Path
    wheel: Path
    temporary_root: Path
    probe_root: Path
    python_lines: tuple[str, ...]


CommandBuilder = Callable[[ScenarioContext, str], tuple[str, ...]]


class CommandResultLike(Protocol):
    @property
    def exit_status(self) -> int | None: ...

    @property
    def start_error(self) -> str | None: ...

    @property
    def cancelled(self) -> bool: ...

    @property
    def timed_out(self) -> bool: ...

    @property
    def output_communication_timed_out(self) -> bool: ...

    @property
    def process_group_cleanup(self) -> str: ...

    @property
    def process_group_cleanup_error(self) -> str | None: ...


OutcomeEvaluator = Callable[[CommandResultLike], str]
CleanupCallback = Callable[[Path], None]


def _worker_command(context: ScenarioContext, scenario_id: str) -> tuple[str, ...]:
    command: tuple[str, ...] = (
        context.python,
        "-B",
        "-m",
        "qualification_probes.scenario_worker",
        "--scenario",
        scenario_id,
        "--candidate-root",
        str(context.candidate_root),
        "--wheel",
        str(context.wheel),
        "--temporary-root",
        str(context.temporary_root),
    )
    for python_line in context.python_lines:
        command += ("--python", python_line)
    return command


def _evaluate(result: CommandResultLike) -> str:
    if (
        result.start_error is not None
        or result.cancelled
        or result.timed_out
        or result.output_communication_timed_out
        or result.process_group_cleanup == "terminated"
        or result.process_group_cleanup_error is not None
    ):
        return "infrastructure_error"
    if result.exit_status == 0:
        return "pass"
    if result.exit_status == 10:
        return "finding"
    return "infrastructure_error"


def _cleanup(_: Path) -> None:
    return None


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    python_line: str | None
    timeout: int
    dependencies: tuple[str, ...]
    command_builder: CommandBuilder = _worker_command
    expected_outcome_evaluator: OutcomeEvaluator = _evaluate
    cleanup_callback: CleanupCallback = _cleanup


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("Q001", "Candidate and environment identity", None, 30, ()),
    Scenario("Q010", "Root build and packaging on 3.14", "3.14", 900, ("Q001",)),
    Scenario("Q011", "Root compatibility on 3.13", "3.13", 900, ("Q001",)),
    Scenario("Q020", "Clean fixture generation", "3.14", 180, ("Q001",)),
    Scenario("Q030", "Add one static page", "3.14", 240, ("Q020",)),
    Scenario("Q031", "Rename a dynamic parameter", "3.14", 240, ("Q020",)),
    Scenario("Q040", "Exact and same-shape collisions", "3.14", 120, ("Q020",)),
    Scenario("Q041", "Unsupported declaration", "3.14", 120, ("Q020",)),
    Scenario("Q042", "Deleted Jinja template", "3.14", 120, ("Q020",)),
    Scenario("Q043", "Controlled-import startup failure", "3.14", 120, ("Q020",)),
    Scenario("Q044", "Request-time generated-route failure", "3.14", 120, ("Q020",)),
    Scenario("Q050", "Starlette and FastAPI hosts", "3.14", 300, ("Q020",)),
    Scenario("Q060", "Full-feature application", None, 1800, ("Q001",)),
    Scenario("Q070", "React and Svelte islands", None, 3600, ("Q001",)),
    Scenario("Q080", "Final identity and cleanup", None, 180, ("Q001",)),
)


def validate_registry(registry: tuple[Scenario, ...]) -> None:
    identifiers = [scenario.id for scenario in registry]
    if len(identifiers) != len(set(identifiers)):
        raise ScenarioError("scenario registry contains a duplicate ID")
    known = set(identifiers)
    for scenario in registry:
        for dependency in scenario.dependencies:
            if dependency not in known:
                raise ScenarioError(
                    f"scenario {scenario.id} has unknown dependency {dependency}"
                )
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {scenario.id: scenario for scenario in registry}

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise ScenarioError(f"scenario dependency cycle includes {identifier}")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in by_id[identifier].dependencies:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in identifiers:
        visit(identifier)


def select_scenarios(
    filters: tuple[str, ...], registry: tuple[Scenario, ...] = SCENARIOS
) -> tuple[Scenario, ...]:
    validate_registry(registry)
    if not registry:
        raise ScenarioError("scenario selection is empty")
    if len(filters) != len(set(filters)):
        raise ScenarioError("duplicate scenario filter")
    by_id = {scenario.id: scenario for scenario in registry}
    if not filters:
        return registry
    unknown = [identifier for identifier in filters if identifier not in by_id]
    if unknown:
        raise ScenarioError(f"unknown scenario: {unknown[0]}")
    selected = set(filters)
    if "Q080" in by_id:
        selected.add("Q080")

    def add_dependencies(identifier: str) -> None:
        for dependency in by_id[identifier].dependencies:
            if dependency not in selected:
                selected.add(dependency)
                add_dependencies(dependency)

    for identifier in tuple(selected):
        add_dependencies(identifier)
    result = tuple(scenario for scenario in registry if scenario.id in selected)
    if not result:
        raise ScenarioError("scenario selection is empty")
    return result
