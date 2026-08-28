from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

import qualification_probes.scenario_worker as worker_module
from qualification_probes.scenario_worker import (
    Finding,
    InfrastructureFailure,
    audit_candidate_mirror,
    clean_candidate_mirror,
    mirror_cleanup,
    run_client_island_check,
    run_full_feature_browser_tests,
)


def test_q010_runs_source_and_consumer_typing_lanes_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    commands: list[list[str | Path]] = []

    @contextmanager
    def no_cleanup(_: Path) -> Generator[None]:
        yield

    def record_run(
        command: list[str | Path], **_: object
    ) -> subprocess.CompletedProcess[bytes]:
        captured = list(command)
        commands.append(captured)
        if captured[:2] == ["uv", "build"]:
            distribution = captured[3]
            assert isinstance(distribution, Path)
            (distribution / "pyganini.whl").write_bytes(b"wheel")
            (distribution / "pyganini.tar.gz").write_bytes(b"sdist")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(worker_module, "mirror_cleanup", no_cleanup)
    monkeypatch.setattr(worker_module, "_run", record_run)

    q010 = getattr(worker_module, "_q" + "010")
    q010(argparse.Namespace(candidate_root=candidate, temporary_root=tmp_path))

    assert commands == [
        ["uv", "lock", "--check"],
        ["uv", "sync", "--locked", "--all-groups", "--python", "3.14"],
        [
            "uv",
            "run",
            "--locked",
            "--python",
            "3.14",
            "ruff",
            "format",
            "--check",
            ".",
        ],
        ["uv", "run", "--locked", "--python", "3.14", "ruff", "check", "."],
        ["uv", "run", "--locked", "--python", "3.14", "mypy", "src/pyganini"],
        ["uv", "run", "--locked", "--python", "3.14", "pyright", "src/pyganini"],
        [
            "uv",
            "run",
            "--locked",
            "--python",
            "3.14",
            "pytest",
            "-q",
            "tests/test_csrf_typing.py",
            "tests/test_sse_typing.py",
            "tests/test_assets.py::test_generated_asset_consumers_are_checked_by_both_type_checkers",
        ],
        [
            "uv",
            "run",
            "--locked",
            "--python",
            "3.14",
            "pytest",
            "-q",
            "tests/test_packaging.py",
            "tests/test_package_install.py",
        ],
        ["uv", "build", "--out-dir", tmp_path / "q010-dist"],
    ]


def test_q041_import_sentinel_is_rejected() -> None:
    reject = getattr(worker_module, "_assert_text_absent", None)
    assert reject is not None

    with pytest.raises(Finding, match="imported an application module"):
        reject(
            b"PYGANINI010 route.py keyword\nqualification static import sentinel\n",
            "qualification static import sentinel",
        )


def test_q042_accepts_early_required_template_failures_for_all_source_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fixture"
    template = root / "app" / "routes" / "users" / "page.jinja"
    template.parent.mkdir(parents=True)
    template.write_text("<h1>Users</h1>\n", encoding="ascii")
    fixture = worker_module.FixtureEnvironment(
        root=root,
        python=Path("python"),
        pyganini=Path("pyganini"),
    )
    commands: list[list[str | Path]] = []

    @contextmanager
    def fixture_context(**_: object) -> Generator[object]:
        yield fixture

    def no_generate(_: object) -> None:
        pass

    def required_template_failure(
        command: list[str | Path], **_: object
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(list(command))
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"",
            stderr=(
                b"app/routes/users/page.jinja: PYGANINI009 route-filesystem: "
                b"cannot inspect required template file: missing\n"
            ),
        )

    monkeypatch.setattr(worker_module, "_fixture", fixture_context)
    monkeypatch.setattr(worker_module, "_generate", no_generate)
    monkeypatch.setattr(worker_module, "_run", required_template_failure)

    q042 = getattr(worker_module, "_q" + "042")
    q042(argparse.Namespace(temporary_root=tmp_path, wheel=tmp_path / "pyganini.whl"))

    assert commands == [
        [Path("pyganini"), "generate", "--app-root", root],
        [Path("pyganini"), "check", "--app-root", root],
        [
            Path("pyganini"),
            "routes",
            "list",
            "--app-root",
            root,
            "--json",
        ],
    ]


def test_q042_reports_generated_mutation_before_unexpected_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fixture"
    template = root / "app" / "routes" / "users" / "page.jinja"
    template.parent.mkdir(parents=True)
    template.write_text("<h1>Users</h1>\n", encoding="ascii")
    generated = root / "app" / "_pyganini" / "asgi.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("ORIGINAL = True\n", encoding="ascii")
    fixture = worker_module.FixtureEnvironment(
        root=root,
        python=Path("python"),
        pyganini=Path("pyganini"),
    )

    @contextmanager
    def fixture_context(**_: object) -> Generator[object]:
        yield fixture

    def no_generate(_: object) -> None:
        pass

    def mutate_then_reject(*_: object, **__: object) -> None:
        generated.write_text("MUTATED = True\n", encoding="ascii")
        raise Finding("command returned 2; expected (0, 1)")

    monkeypatch.setattr(worker_module, "_fixture", fixture_context)
    monkeypatch.setattr(worker_module, "_generate", no_generate)
    monkeypatch.setattr(worker_module, "_run", mutate_then_reject)

    q042 = getattr(worker_module, "_q" + "042")
    with pytest.raises(Finding, match="Q042 generate changed generated products"):
        q042(
            argparse.Namespace(temporary_root=tmp_path, wheel=tmp_path / "pyganini.whl")
        )


@pytest.mark.parametrize(
    "case",
    (
        "exit_zero",
        "wrong_code",
        "wrong_phase",
        "wrong_path",
        "wrong_family",
        "stdout_product",
        "traceback",
        "generated_mutation",
    ),
)
def test_q042_contract_rejects_one_fact_mutations(case: str) -> None:
    assert_result = getattr(worker_module, "_assert_q042_" + "command_result")
    accepted_stderr = (
        b"app/routes/users/page.jinja: PYGANINI009 route-filesystem: "
        b"cannot inspect required template file: missing\n"
    )
    baseline = subprocess.CompletedProcess(
        ["pyganini", "generate"], 1, stdout=b"", stderr=accepted_stderr
    )
    assert_result(
        baseline,
        command_name="generate",
        generated_unchanged=True,
    )

    result = baseline
    generated_unchanged = True
    if case == "exit_zero":
        result = subprocess.CompletedProcess(
            baseline.args, 0, stdout=baseline.stdout, stderr=baseline.stderr
        )
    elif case == "wrong_code":
        result = subprocess.CompletedProcess(
            baseline.args,
            1,
            stdout=b"",
            stderr=accepted_stderr.replace(b"PYGANINI009", b"PYGANINI005"),
        )
    elif case == "wrong_phase":
        result = subprocess.CompletedProcess(
            baseline.args,
            1,
            stdout=b"",
            stderr=accepted_stderr.replace(b"route-filesystem", b"generated-state"),
        )
    elif case == "wrong_path":
        result = subprocess.CompletedProcess(
            baseline.args,
            1,
            stdout=b"",
            stderr=accepted_stderr.replace(
                b"app/routes/users/page.jinja", b"app/routes/page.jinja"
            ),
        )
    elif case == "wrong_family":
        result = subprocess.CompletedProcess(
            baseline.args,
            1,
            stdout=b"",
            stderr=accepted_stderr.replace(
                b"cannot inspect required template file", b"cannot read route source"
            ),
        )
    elif case == "stdout_product":
        result = subprocess.CompletedProcess(
            baseline.args,
            1,
            stdout=b'{"schema":"pyganini.routes.v1","routes":[]}\n',
            stderr=accepted_stderr,
        )
    elif case == "traceback":
        result = subprocess.CompletedProcess(
            baseline.args,
            1,
            stdout=b"",
            stderr=accepted_stderr + b"Traceback (most recent call last):\n",
        )
    elif case == "generated_mutation":
        generated_unchanged = False

    with pytest.raises(Finding, match="Q042"):
        assert_result(
            result,
            command_name="generate",
            generated_unchanged=generated_unchanged,
        )


def test_q043_accepts_dispatch_wrapper_with_application_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fixture"
    for package in (
        root / "app",
        root / "app" / "_pyganini",
        root / "app" / "routes",
        root / "app" / "routes" / "users",
    ):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="ascii")
    handlers = root / "app" / "routes" / "users" / "handlers.py"
    handlers.write_text("VALUE = 1\n", encoding="ascii")
    (handlers.parent / "route.py").write_text(
        "from . import handlers\n", encoding="ascii"
    )
    (root / "app" / "_pyganini" / "asgi.py").write_text(
        "class DispatchError(RuntimeError):\n"
        "    code = 'PYGANINI012'\n"
        "    phase = 'route-import'\n"
        "    path = 'app/routes/users/route.py'\n"
        "try:\n"
        "    import app.routes.users.route\n"
        "except RuntimeError as error:\n"
        "    raise DispatchError(\n"
        "        \"cannot import route module 'app.routes.users.route'\"\n"
        "    ) from error\n",
        encoding="ascii",
    )
    fixture = worker_module.FixtureEnvironment(
        root=root,
        python=Path(sys.executable),
        pyganini=Path("pyganini"),
    )
    source_commands: list[str] = []
    check_stderr = b""

    @contextmanager
    def fixture_context(**_: object) -> Generator[object]:
        yield fixture

    def no_generate(_: object) -> None:
        pass

    def passing_source_command(
        _: object, arguments: list[str | Path]
    ) -> subprocess.CompletedProcess[bytes]:
        if arguments[0] == "check":
            source_commands.append("check")
            return subprocess.CompletedProcess(
                arguments, 0, stdout=b"", stderr=check_stderr
            )
        source_commands.append("routes list --json")
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=b'{"schema":"pyganini.routes.v1","routes":[]}\n',
            stderr=b"",
        )

    monkeypatch.setattr(worker_module, "_fixture", fixture_context)
    monkeypatch.setattr(worker_module, "_generate", no_generate)
    monkeypatch.setattr(worker_module, "_q043_source_command", passing_source_command)

    q043 = getattr(worker_module, "_q" + "043")
    q043(argparse.Namespace(temporary_root=tmp_path, wheel=tmp_path / "pyganini.whl"))

    assert source_commands == ["check", "routes list --json"]

    handlers.write_text("VALUE = 1\n", encoding="ascii")
    source_commands.clear()
    check_stderr = b"PYGANINI-Q043-IMPORT:app.routes.users.handlers\n"
    with pytest.raises(
        Finding, match="Q043 source-only command imported application handler"
    ):
        q043(
            argparse.Namespace(temporary_root=tmp_path, wheel=tmp_path / "pyganini.whl")
        )


def test_q043_source_trace_records_caught_handler_import(tmp_path: Path) -> None:
    handlers = tmp_path / "app" / "routes" / "users" / "handlers.py"
    handlers.parent.mkdir(parents=True)
    handlers.write_text(
        'raise RuntimeError("qualification import failure")\n', encoding="ascii"
    )
    entrypoint = tmp_path / "bin" / "pyganini"
    entrypoint.parent.mkdir()
    entrypoint.write_text("VALUE = 1\n", encoding="ascii")
    fixture = worker_module.FixtureEnvironment(
        root=tmp_path,
        python=Path(sys.executable),
        pyganini=entrypoint,
    )
    source_command = getattr(worker_module, "_q043_" + "source_command")

    accepted = source_command(fixture, ["check"])
    assert accepted.returncode == 0
    assert b"PYGANINI-Q043-IMPORT:app.routes.users.handlers" not in accepted.stderr

    entrypoint.write_text(
        "try:\n    import app.routes.users.handlers\nexcept RuntimeError:\n    pass\n",
        encoding="ascii",
    )
    imported = source_command(fixture, ["check"])
    assert imported.returncode == 0
    assert b"PYGANINI-Q043-IMPORT:app.routes.users.handlers" in imported.stderr


@pytest.mark.parametrize(
    "case",
    (
        "startup_accepted",
        "direct_original_exception",
        "wrong_code",
        "wrong_phase",
        "wrong_path",
        "wrong_message",
        "missing_cause",
        "wrong_cause_identity",
        "wrong_cause_type",
        "wrong_cause_message",
        "missing_application_frame",
        "missing_sentinel_line",
        "source_sentinel_execution",
        "source_command_import",
        "generated_mutation",
    ),
)
def test_q043_contract_rejects_one_fact_mutations(case: str) -> None:
    assert_observation = getattr(worker_module, "_assert_q043_" + "observation")
    baseline: dict[str, object] = {
        "startup_raised": True,
        "wrapper_type": "DispatchError",
        "wrapper_code": "PYGANINI012",
        "wrapper_phase": "route-import",
        "wrapper_path": "app/routes/users/route.py",
        "wrapper_message": "cannot import route module 'app.routes.users.route'",
        "cause_present": True,
        "cause_is_runtime_error": True,
        "cause_type": "RuntimeError",
        "cause_message": "qualification import failure",
        "cause_traceback": (
            '  File "app/routes/users/handlers.py", line 3, in <module>\n'
            '    raise RuntimeError("qualification import failure")\n'
        ),
    }
    assert_observation(
        baseline,
        source_only_sentinel_absent=True,
        source_only_import_absent=True,
        generated_unchanged=True,
    )

    observation = dict(baseline)
    source_only_sentinel_absent = True
    source_only_import_absent = True
    generated_unchanged = True
    mutations: dict[str, tuple[str, object]] = {
        "startup_accepted": ("startup_raised", False),
        "direct_original_exception": ("wrapper_type", "RuntimeError"),
        "wrong_code": ("wrapper_code", "PYGANINI014"),
        "wrong_phase": ("wrapper_phase", "route-response"),
        "wrong_path": ("wrapper_path", "app/routes/users/handlers.py"),
        "wrong_message": ("wrapper_message", "qualification import failure"),
        "missing_cause": ("cause_present", False),
        "wrong_cause_identity": ("cause_is_runtime_error", False),
        "wrong_cause_type": ("cause_type", "ValueError"),
        "wrong_cause_message": ("cause_message", "different failure"),
        "missing_application_frame": (
            "cause_traceback",
            '    raise RuntimeError("qualification import failure")\n',
        ),
        "missing_sentinel_line": (
            "cause_traceback",
            '  File "app/routes/users/handlers.py", line 3, in <module>\n',
        ),
    }
    if case in mutations:
        key, value = mutations[case]
        observation[key] = value
    elif case == "source_sentinel_execution":
        source_only_sentinel_absent = False
    elif case == "source_command_import":
        source_only_import_absent = False
    elif case == "generated_mutation":
        generated_unchanged = False

    with pytest.raises(Finding, match="Q043"):
        assert_observation(
            observation,
            source_only_sentinel_absent=source_only_sentinel_absent,
            source_only_import_absent=source_only_import_absent,
            generated_unchanged=generated_unchanged,
        )


def test_expected_runtime_failure_rejects_generated_product_mutation(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "app" / "_pyganini" / "routes.py"
    generated.parent.mkdir(parents=True)
    generated.write_text("before\n", encoding="ascii")
    guard = getattr(worker_module, "generated_products_unchanged", None)
    assert guard is not None

    with (
        pytest.raises(Finding, match="Q044 changed generated source state"),
        guard(tmp_path, "Q044"),
    ):
        generated.write_text("after\n", encoding="ascii")


def test_q044_checks_each_request_failure_path_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fixture"
    handlers = root / "app" / "routes" / "problem" / "handlers.py"
    handlers.parent.mkdir(parents=True)
    handlers.write_text("def page(request): raise RuntimeError\n", encoding="ascii")
    fixture = worker_module.FixtureEnvironment(
        root=root,
        python=Path("python"),
        pyganini=Path("pyganini"),
    )
    guarded_paths: list[str] = []

    @contextmanager
    def fixture_context(**kwargs: object) -> Generator[object]:
        yield fixture

    @contextmanager
    def record_guard(candidate: Path, scenario: str) -> Generator[None]:
        assert candidate == root
        guarded_paths.append(scenario)
        yield

    def no_generate(selected: object) -> None:
        pass

    def no_run(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(worker_module, "_fixture", fixture_context)
    monkeypatch.setattr(worker_module, "_generate", no_generate)
    monkeypatch.setattr(worker_module, "_run", no_run)
    monkeypatch.setattr(worker_module, "generated_products_unchanged", record_guard)

    q044 = getattr(worker_module, "_q" + "044")
    q044(argparse.Namespace(temporary_root=tmp_path, wheel=tmp_path / "pyganini.whl"))

    assert guarded_paths == ["Q044 callback failure", "Q044 post-start failure"]


def test_client_island_check_nonzero_is_infrastructure_incomplete(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "check-client-islands.sh"
    script.parent.mkdir()
    script.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="ascii")

    with pytest.raises(InfrastructureFailure, match="command returned 7"):
        run_client_island_check(tmp_path)


def test_full_feature_browser_failure_is_infrastructure_incomplete(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "uv"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 7\n", encoding="ascii")
    executable.chmod(0o755)

    with pytest.raises(InfrastructureFailure, match="command returned 7"):
        run_full_feature_browser_tests(
            tmp_path,
            {"PATH": str(executable.parent)},
        )


def test_dirty_candidate_mirror_is_infrastructure_incomplete(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("clean\n", encoding="ascii")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Qualification Test",
            "-c",
            "user.email=qualification@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    tracked.write_text("dirty\n", encoding="ascii")

    with pytest.raises(InfrastructureFailure, match="candidate mirror is dirty"):
        audit_candidate_mirror(tmp_path)


def test_cleanup_residue_is_infrastructure_incomplete(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("clean\n", encoding="ascii")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Qualification Test",
            "-c",
            "user.email=qualification@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    tracked.write_text("dirty\n", encoding="ascii")

    with pytest.raises(InfrastructureFailure, match="scenario cleanup"):
        clean_candidate_mirror(tmp_path)


def test_cleanup_failure_retains_primary_infrastructure_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_cleanup(_: Path) -> None:
        raise InfrastructureFailure("mirror residue")

    monkeypatch.setattr(
        "qualification_probes.scenario_worker.clean_candidate_mirror",
        fail_cleanup,
    )

    with (
        pytest.raises(
            InfrastructureFailure,
            match=r"browser startup failed.*mirror cleanup failed.*mirror residue",
        ),
        mirror_cleanup(tmp_path),
    ):
        raise InfrastructureFailure("browser startup failed")
