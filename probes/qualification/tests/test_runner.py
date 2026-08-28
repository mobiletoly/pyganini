from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest

import qualification_probes.runner as runner_module
from qualification_probes.evidence import EvidenceError
from qualification_probes.identity import (
    CandidateMirror,
    IdentityError,
    capture_candidate,
)
from qualification_probes.runner import (
    CommandResult,
    ProcessCleanupResult,
    QualificationError,
    build_candidate_report,
    build_environment,
    capture_environment_report,
    capture_process_baseline,
    combine_infrastructure_errors,
    finalize_q080_record,
    main,
    run_command,
    run_scenario_cleanup,
    run_scenario_command,
    temporary_processes,
    validate_paths,
)
from qualification_probes.scenarios import SCENARIOS, Scenario, ScenarioContext


def preserve_test_process_identity(process_id: int, started: str) -> str:
    return started


def fixed_test_process_identity(process_id: int) -> str:
    return "darwin:7"


def test_run_command_preserves_stream_bytes_and_exit_status(tmp_path: Path) -> None:
    result = run_command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'out\\x00'); "
            "sys.stderr.buffer.write(b'err\\n'); raise SystemExit(7)",
        ],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result.exit_status == 7
    assert result.stdout == b"out\x00"
    assert result.stderr == b"err\n"
    assert result.start_error is None


def test_run_command_times_out_and_reaps_process_group(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        timeout=0.05,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result.timed_out is True
    assert result.exit_status is not None
    assert result.process_group_cleanup in {"clean", "terminated"}
    assert result.process_group_cleanup_error is None


def test_run_command_reaps_descendants_after_nonzero_exit(tmp_path: Path) -> None:
    script = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(30)'], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "raise SystemExit(7)"
    )

    result = run_command(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result.exit_status == 7
    assert result.timed_out is False
    assert result.process_group_cleanup == "terminated"
    assert result.process_group_cleanup_error is None


def test_run_command_reaps_process_group_on_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "child.pid"
    original_communicate = cast(
        Callable[
            [subprocess.Popen[bytes], bytes | None, float | None],
            tuple[bytes, bytes],
        ],
        subprocess.Popen.communicate,  # pyright: ignore[reportUnknownMemberType]
    )
    interrupt_pending = True

    def communicate(
        process: subprocess.Popen[bytes],
        input: bytes | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes, bytes]:
        nonlocal interrupt_pending
        if interrupt_pending and process.args == (sys.executable, "-c", script):
            interrupt_pending = False
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            raise KeyboardInterrupt
        return original_communicate(process, input, timeout)

    monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
    script = (
        "import os, pathlib, time; "
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )

    result = run_command(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result.cancelled is True
    assert result.process_group_cleanup in {"clean", "terminated"}
    assert result.process_group_cleanup_error is None
    assert SCENARIOS[0].expected_outcome_evaluator(result) == "infrastructure_error"
    process_group = int(marker.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.killpg(process_group, 0)


def test_successful_scenario_with_terminated_survivor_is_infrastructure_error(
    tmp_path: Path,
) -> None:
    result = CommandResult(
        command=("worker",),
        cwd=tmp_path,
        monotonic_start_ms=0,
        duration_ms=1,
        exit_status=0,
        stdout=b"",
        stderr=b"",
        start_error=None,
        cancelled=False,
        timed_out=False,
        output_communication_timed_out=False,
        process_group_cleanup="terminated",
        process_group_cleanup_error=None,
    )

    assert SCENARIOS[0].expected_outcome_evaluator(result) == "infrastructure_error"


def test_run_command_records_output_timeout_after_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeProcess:
        pid = 1234
        returncode: int | None = None
        communicate_count = 0

        def communicate(self, *, timeout: float) -> tuple[bytes, bytes]:
            self.communicate_count += 1
            if self.communicate_count == 1:
                raise KeyboardInterrupt
            raise subprocess.TimeoutExpired(
                cmd=("fake",),
                timeout=timeout,
                output=b"partial",
                stderr=b"communication stalled",
            )

    process = FakeProcess()

    def fake_popen(*_: object, **__: object) -> FakeProcess:
        return process

    def failed_cleanup(
        _: object, *, grace_seconds: float = 5, **kwargs: object
    ) -> tuple[str, str]:
        assert grace_seconds == 5
        return "failed", "process group survived"

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (999, ((1234, 1, 1234, os.getuid(), "darwin:7"),)),
    )
    monkeypatch.setattr(
        runner_module, "_exact_process_identity", fixed_test_process_identity
    )
    monkeypatch.setattr(
        "qualification_probes.runner._terminate_process_group", failed_cleanup
    )

    result = run_command(
        ["fake"],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result.cancelled is True
    assert result.stdout == b"partial"
    assert result.stderr == b"communication stalled"
    assert result.process_group_cleanup == "failed"
    assert result.process_group_cleanup_error == (
        "process group survived; "
        "cancelled process did not close output streams after cleanup"
    )


def test_run_command_records_first_output_timeout_after_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeProcess:
        pid = 1234
        returncode: int | None = None
        communicate_count = 0

        def communicate(self, *, timeout: float) -> tuple[bytes, bytes]:
            self.communicate_count += 1
            if self.communicate_count == 1:
                raise KeyboardInterrupt
            if self.communicate_count == 2:
                raise subprocess.TimeoutExpired(
                    cmd=("fake",),
                    timeout=timeout,
                    output=b"partial",
                    stderr=b"communication stalled",
                )
            return b"complete", b""

    process = FakeProcess()

    def fake_popen(*_: object, **__: object) -> FakeProcess:
        return process

    def clean_group(
        _: object, *, grace_seconds: float = 5, **kwargs: object
    ) -> tuple[str, None]:
        assert grace_seconds == 5
        return "clean", None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (999, ((1234, 1, 1234, os.getuid(), "darwin:7"),)),
    )
    monkeypatch.setattr(
        runner_module, "_exact_process_identity", fixed_test_process_identity
    )
    monkeypatch.setattr(
        "qualification_probes.runner._terminate_process_group", clean_group
    )

    result = run_command(
        ["fake"],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result.cancelled is True
    assert result.output_communication_timed_out is True
    assert result.process_group_cleanup_error == (
        "cancelled process did not close output streams after cleanup"
    )


def test_run_command_never_uses_unbounded_communicate_after_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeProcess:
        pid = 1234
        returncode: int | None = None
        communicate_count = 0

        def communicate(self, *, timeout: float) -> tuple[bytes, bytes]:
            self.communicate_count += 1
            raise subprocess.TimeoutExpired(
                cmd=("fake",),
                timeout=timeout,
                output=b"partial",
                stderr=b"pipe open",
            )

    process = FakeProcess()

    def fake_popen(*_: object, **__: object) -> FakeProcess:
        return process

    def clean_group(
        _: object, *, grace_seconds: float = 5, **kwargs: object
    ) -> tuple[str, None]:
        assert grace_seconds == 5
        return "clean", None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (999, ((1234, 1, 1234, os.getuid(), "darwin:7"),)),
    )
    monkeypatch.setattr(
        runner_module, "_exact_process_identity", fixed_test_process_identity
    )
    monkeypatch.setattr(
        "qualification_probes.runner._terminate_process_group", clean_group
    )

    result = run_command(
        ["fake"],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert process.communicate_count == 2
    assert result.timed_out is True
    assert result.output_communication_timed_out is True
    assert result.process_group_cleanup_error == (
        "timed-out process did not close output streams after cleanup"
    )


def test_environment_metadata_is_captured_while_temporary_root_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary_root = tmp_path / "qualification"
    temporary_root.mkdir()
    (temporary_root / "tmp").mkdir()
    environment = {
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(temporary_root / "tmp"),
        "UV_CACHE_DIR": str(temporary_root / "uv-cache"),
        "npm_config_cache": str(temporary_root / "npm-cache"),
    }
    calls: list[tuple[str, ...]] = []

    def fake_tool_output(
        command: list[str], *, environment: object, **kwargs: object
    ) -> str:
        assert temporary_root.exists()
        calls.append(tuple(command))
        if command[:3] == ["uv", "python", "find"]:
            return sys.executable
        return "tool output"

    monkeypatch.setattr("qualification_probes.runner._tool_output", fake_tool_output)

    report = capture_environment_report(
        environment=environment,
        python_lines=("3.14", "3.13"),
        scenario_ids=("Q001", "Q080"),
    )

    assert report["scenario_inventory"] == ["Q001", "Q080"]
    assert ("uv", "--version") in calls
    assert ("uv", "python", "find", "3.14") in calls


def test_environment_metadata_timeout_is_infrastructure_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timed_out_command(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(
            command=("uv", "python", "find", "3.14"),
            cwd=tmp_path,
            monotonic_start_ms=0,
            duration_ms=30_000,
            exit_status=None,
            stdout=b"",
            stderr=b"",
            start_error=None,
            cancelled=False,
            timed_out=True,
            output_communication_timed_out=False,
            process_group_cleanup="terminated",
            process_group_cleanup_error=None,
        )

    monkeypatch.setattr(runner_module, "run_command", timed_out_command)

    with pytest.raises(QualificationError, match="metadata command timed out"):
        capture_environment_report(
            environment={"PATH": "/usr/bin:/bin"},
            python_lines=("3.14",),
            scenario_ids=("Q001", "Q080"),
        )


def test_environment_metadata_survivor_termination_is_infrastructure_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def command_with_survivor(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(
            command=("uv", "--version"),
            cwd=tmp_path,
            monotonic_start_ms=0,
            duration_ms=1,
            exit_status=0,
            stdout=b"uv 1.0",
            stderr=b"",
            start_error=None,
            cancelled=False,
            timed_out=False,
            output_communication_timed_out=False,
            process_group_cleanup="terminated",
            process_group_cleanup_error=None,
        )

    monkeypatch.setattr(runner_module, "run_command", command_with_survivor)

    with pytest.raises(QualificationError, match="owned survivor"):
        capture_environment_report(
            environment={"PATH": "/usr/bin:/bin"},
            python_lines=("3.14",),
            scenario_ids=("Q001", "Q080"),
        )


def test_identity_git_survivor_termination_is_identity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def command_with_survivor(*args: object, **kwargs: object) -> CommandResult:
        return CommandResult(
            command=("git", "status"),
            cwd=tmp_path,
            monotonic_start_ms=0,
            duration_ms=1,
            exit_status=0,
            stdout=b"",
            stderr=b"",
            start_error=None,
            cancelled=False,
            timed_out=False,
            output_communication_timed_out=False,
            process_group_cleanup="terminated",
            process_group_cleanup_error=None,
        )

    monkeypatch.setattr(runner_module, "run_command", command_with_survivor)
    bounded_runner = runner_module.build_identity_command_runner(
        runner_module.ProcessOwnershipTracker()
    )

    with pytest.raises(IdentityError, match="owned survivor"):
        bounded_runner(
            ("git", "status"),
            cwd=tmp_path,
            environment={"PATH": "/usr/bin:/bin"},
            check=True,
            failure_label="candidate Git command",
        )


def test_environment_metadata_commands_share_durable_ownership_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = runner_module.ProcessOwnershipTracker()
    observed: list[object] = []

    def successful_command(command: list[str], **kwargs: object) -> CommandResult:
        observed.append(kwargs.get("ownership_tracker"))
        output = (
            sys.executable.encode("utf-8")
            if command[:3] == ["uv", "python", "find"]
            else b"version"
        )
        return CommandResult(
            command=tuple(command),
            cwd=tmp_path,
            monotonic_start_ms=0,
            duration_ms=1,
            exit_status=0,
            stdout=output,
            stderr=b"",
            start_error=None,
            cancelled=False,
            timed_out=False,
            output_communication_timed_out=False,
            process_group_cleanup="clean",
            process_group_cleanup_error=None,
        )

    monkeypatch.setattr(runner_module, "run_command", successful_command)

    capture_environment_report(
        environment={"PATH": "/usr/bin:/bin"},
        python_lines=("3.14",),
        scenario_ids=("Q001", "Q080"),
        ownership_tracker=tracker,
    )

    assert observed
    assert all(item is tracker for item in observed)


def test_scenarios_receive_isolated_caches_and_inherited_bytecode_protection(
    tmp_path: Path,
) -> None:
    q001 = build_environment(tmp_path, "marker", "Q001")
    q020 = build_environment(tmp_path, "marker", "Q020")

    assert q001["UV_CACHE_DIR"] != q020["UV_CACHE_DIR"]
    assert q001["npm_config_cache"] != q020["npm_config_cache"]
    assert q001["PYTHONDONTWRITEBYTECODE"] == "1"
    assert q020["PYTHONDONTWRITEBYTECODE"] == "1"


def test_process_table_rejects_malformed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProcess:
        pid = 999
        returncode = 0

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            return b"123 1\n", b""

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    def exact_identity(process_id: int) -> str:
        return "darwin:7"

    def process_group(process_id: int) -> int:
        return 999

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_module, "_exact_process_identity", exact_identity)
    monkeypatch.setattr(os, "getpgid", process_group)

    with pytest.raises(QualificationError, match="malformed process table row"):
        capture_process_baseline()


def test_process_table_timeout_uses_identity_bound_signalling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = (999, os.getpid(), 999, os.getuid(), "darwin:7")
    signals: list[tuple[object, int]] = []

    class FakeProcess:
        pid = 999
        returncode = None
        attempts = 0

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            self.attempts += 1
            if self.attempts == 1:
                raise subprocess.TimeoutExpired(["ps"], timeout)
            return b"", b""

        def kill(self) -> None:
            pytest.fail("numeric Popen.kill is forbidden")

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        return FakeProcess()

    def exact_identity(process_id: int) -> str:
        return "darwin:7"

    def process_group(process_id: int) -> int:
        return 999

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_module, "_exact_process_identity", exact_identity)
    monkeypatch.setattr(os, "getpgid", process_group)

    def signal_identity(process: object, selected_signal: int) -> tuple[bool, None]:
        signals.append((process, selected_signal))
        return True, None

    monkeypatch.setattr(runner_module, "_signal_process_identity", signal_identity)

    with pytest.raises(QualificationError, match="temporary-process audit timed out"):
        capture_process_baseline()

    assert signals == [(entry, signal.SIGKILL)]


def test_ownership_tracker_retains_same_pid_generations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = runner_module.ProcessOwnershipTracker()
    current = [(123, 1, 123, os.getuid(), "old-start")]
    monkeypatch.setattr(runner_module, "_process_table", lambda: (999, tuple(current)))
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    observe = getattr(tracker, "_ob" + "serve")
    register = getattr(tracker, "_register_root_" + "identity")

    def exact_identity(process_id: int) -> str:
        return current[0][4]

    monkeypatch.setattr(runner_module, "_exact_process_identity", exact_identity)

    old_identity = register(123)
    observe(123, old_identity)
    current[:] = [(123, 1, 123, os.getuid(), "new-start")]
    new_identity = register(123)
    observe(123, new_identity)

    identities, errors = tracker.snapshot()
    assert identities == frozenset({(123, "old-start"), (123, "new-start")})
    assert errors == ()


def test_ownership_tracker_rejects_reused_root_and_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = runner_module.ProcessOwnershipTracker()
    current = [(123, 1, 123, os.getuid(), "owned-start")]
    monkeypatch.setattr(runner_module, "_process_table", lambda: (999, tuple(current)))
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    observe = getattr(tracker, "_ob" + "serve")
    register = getattr(tracker, "_register_root_" + "identity")

    def exact_identity(process_id: int) -> str:
        return current[0][4]

    monkeypatch.setattr(runner_module, "_exact_process_identity", exact_identity)

    root_identity = register(123)
    observe(123, root_identity)
    current[:] = [
        (123, 1, 123, os.getuid(), "reused-root"),
        (124, 1, 123, os.getuid(), "unrelated-group-member"),
    ]
    observe(123, root_identity)

    identities, errors = tracker.snapshot()
    assert identities == frozenset({(123, "owned-start")})
    assert errors == ()


def test_identity_git_runner_is_bounded_and_uses_shared_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = runner_module.ProcessOwnershipTracker()
    calls: list[dict[str, object]] = []

    def command(command_arguments: Sequence[str], **kwargs: object) -> CommandResult:
        calls.append(dict(kwargs))
        return CommandResult(
            command=tuple(command_arguments),
            cwd=tmp_path,
            monotonic_start_ms=0,
            duration_ms=1,
            exit_status=0,
            stdout=b"bounded output",
            stderr=b"",
            start_error=None,
            cancelled=False,
            timed_out=False,
            output_communication_timed_out=False,
            process_group_cleanup="clean",
            process_group_cleanup_error=None,
        )

    monkeypatch.setattr(runner_module, "run_command", command)
    factory = getattr(runner_module, "build_identity_" + "command_runner")
    bounded = factory(tracker)

    output = bounded(
        ("git", "status"),
        cwd=tmp_path,
        environment={"PATH": "/usr/bin:/bin"},
        check=True,
        failure_label="candidate Git command",
    )

    assert output == b"bounded output"
    assert calls == [
        {
            "cwd": tmp_path,
            "timeout": 30,
            "environment": {"PATH": "/usr/bin:/bin"},
            "ownership_tracker": tracker,
        }
    ]


def test_command_cleanup_accepts_current_same_pid_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = runner_module.ProcessOwnershipTracker()
    current = [(123, 1, 123, os.getuid(), "old-start")]
    monkeypatch.setattr(runner_module, "_process_table", lambda: (999, tuple(current)))
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    observe = getattr(tracker, "_ob" + "serve")
    register = getattr(tracker, "_register_root_" + "identity")

    def exact_identity(process_id: int) -> str:
        return current[0][4]

    monkeypatch.setattr(runner_module, "_exact_process_identity", exact_identity)
    old_identity = register(123)
    observe(123, old_identity)
    current[:] = [(123, 1, 123, os.getuid(), "new-start")]
    new_identity = register(123)
    observe(123, new_identity)
    terminated: list[tuple[tuple[int, int, int, int, str], ...]] = []

    def terminate_group(process_group: int, **kwargs: object) -> tuple[str, None]:
        assert process_group == 123
        expected = kwargs.get("expected_processes")
        assert isinstance(expected, tuple)
        terminated.append(cast(tuple[tuple[int, int, int, int, str], ...], expected))
        return "terminated", None

    monkeypatch.setattr(runner_module, "_terminate_process_group_id", terminate_group)

    class FakeProcess:
        pid = 123

    terminate = getattr(runner_module, "_terminate_process_" + "group")
    status, error = terminate(FakeProcess(), ownership_tracker=tracker)

    assert status == "terminated"
    assert error is None
    assert terminated == [((123, 1, 123, os.getuid(), "new-start"),)]


def test_linux_process_environment_permission_failure_is_not_process_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny(_: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    monkeypatch.setattr(Path, "read_bytes", deny)
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (999, ((123, 1, 123, os.getuid(), "start"),)),
    )

    with pytest.raises(QualificationError, match="environment audit failed"):
        temporary_processes(frozenset(), "marker")


def test_reused_baseline_pid_is_audited(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = "reused-pid-marker"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (999, ((123, 1, 123, os.getuid(), "new-start"),)),
    )

    def marked_environment(process_id: int) -> bytes:
        return f"PYGANINI_QUALIFICATION_PROCESS_MARKER={marker}\0".encode("ascii")

    monkeypatch.setattr(runner_module, "_process_environment", marked_environment)

    survivors = temporary_processes(frozenset({(123, "old-start")}), marker)

    assert survivors == ("pid=123 ppid=1 pgid=123 start=new-start",)


def test_process_audit_fails_closed_on_scrubbed_descendant_by_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "lineage-marker"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (
            999,
            (
                (123, 1, 123, os.getuid(), "parent-start"),
                (124, 123, 124, os.getuid(), "child-start"),
            ),
        ),
    )

    def environment(process_id: int) -> bytes:
        if process_id == 123:
            return f"PYGANINI_QUALIFICATION_PROCESS_MARKER={marker}\0".encode("ascii")
        return b""

    monkeypatch.setattr(runner_module, "_process_environment", environment)

    with pytest.raises(QualificationError, match="empty environment for owned pid 124"):
        temporary_processes(frozenset(), marker)


def test_process_audit_excludes_unrelated_reused_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "group-reuse-marker"
    parent = (123, 1, 456, os.getuid(), "parent-start")
    unrelated = (124, 1, 456, os.getuid(), "unrelated-start")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    monkeypatch.setattr(
        runner_module, "_process_table", lambda: (999, (parent, unrelated))
    )

    def environment(process_id: int) -> bytes:
        if process_id == 123:
            return f"PYGANINI_QUALIFICATION_PROCESS_MARKER={marker}\0".encode("ascii")
        return b"UNRELATED=1\0"

    monkeypatch.setattr(runner_module, "_process_environment", environment)
    audit = getattr(runner_module, "_audit_temporary_" + "processes")

    detected, errors = audit(frozenset(), marker)

    assert detected == (parent,)
    assert errors == ()


def test_process_audit_fails_closed_on_replaced_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module, "_entry_exact_identity", preserve_test_process_identity
    )
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: (999, ((123, 1, 123, os.getuid(), "start"),)),
    )

    def replaced_environment(process_id: int) -> bytes:
        return b"PYGANINI_QUALIFICATION_PROCESS_MARKER=replaced\0"

    monkeypatch.setattr(runner_module, "_process_environment", replaced_environment)

    with pytest.raises(QualificationError, match="replaced marker"):
        temporary_processes(frozenset(), "expected")


def test_detected_processes_are_terminated_and_reaudited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = getattr(runner_module, "cleanup_temporary_processes", None)
    assert cleanup is not None
    detected = ((123, 1, 456, os.getuid(), "start"),)
    audits = iter(((detected, ()), ((), ())))
    terminated: list[int] = []

    def audit(baseline: object, marker: str, **kwargs: object) -> object:
        return next(audits)

    monkeypatch.setattr(runner_module, "_audit_temporary_processes", audit)

    def terminate(process_group: int, **kwargs: object) -> tuple[str, None]:
        terminated.append(process_group)
        return "terminated", None

    monkeypatch.setattr(
        runner_module,
        "_terminate_process_group_id",
        terminate,
    )

    result = cleanup(frozenset(), "marker")

    assert terminated == [456]
    assert result.detected == ("pid=123 ppid=1 pgid=456 start=start",)
    assert result.lingering == ()
    assert result.error is None


def test_survivor_cleanup_revalidates_group_identity_before_signalling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function_name = "_terminate_process_group" + "_id"
    terminate = getattr(runner_module, function_name)
    signals: list[tuple[int, int]] = []

    def record_signal(group: int, selected_signal: int) -> None:
        signals.append((group, selected_signal))

    def reject_replaced_process(
        process: object, selected_signal: int
    ) -> tuple[bool, None]:
        return False, None

    monkeypatch.setattr(
        runner_module,
        "_signal_process_identity",
        reject_replaced_process,
    )
    monkeypatch.setattr(os, "killpg", record_signal)

    status, error = terminate(
        456,
        expected_processes=((123, 1, 456, os.getuid(), "owned-start"),),
    )

    assert status == "clean"
    assert error is None
    assert signals == []


def test_survivor_cleanup_signals_only_identity_bound_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = (123, 1, 456, os.getuid(), "darwin:7")
    signalled: list[tuple[int, int]] = []

    def signal_identity(
        process: object, selected_signal: int
    ) -> tuple[bool, str | None]:
        assert process == entry
        signalled.append((entry[0], selected_signal))
        return True, None

    monkeypatch.setattr(runner_module, "_signal_process_identity", signal_identity)

    def forbid_group_signal(*arguments: object) -> None:
        pytest.fail("numeric process-group signaling is forbidden")

    def no_owned_processes(
        entries: tuple[tuple[int, int, int, int, str], ...],
    ) -> tuple[tuple[int, int, int, int, str], ...]:
        return ()

    monkeypatch.setattr(os, "killpg", forbid_group_signal)
    monkeypatch.setattr(runner_module, "_owned_processes_alive", no_owned_processes)

    terminate = getattr(runner_module, "_terminate_process_group" + "_id")
    status, error = terminate(
        456,
        expected_processes=(entry,),
    )

    assert status == "terminated"
    assert error is None
    assert signalled == [(123, signal.SIGTERM)]


def test_known_owned_process_is_retained_when_environment_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = (123, 1, 123, os.getuid(), "darwin:7")
    monkeypatch.setattr(runner_module, "_process_table", lambda: (999, (entry,)))

    def unreadable(_: int) -> bytes:
        raise QualificationError("environment denied")

    monkeypatch.setattr(runner_module, "_process_environment", unreadable)

    audit = getattr(runner_module, "_audit_temporary" + "_processes")
    detected, errors = audit(
        frozenset(),
        "marker",
        known_owned=frozenset({(123, "darwin:7")}),
    )

    assert detected == (entry,)
    assert errors == ("environment denied",)


def test_detached_marker_stripped_child_remains_durably_attributed(
    tmp_path: Path,
) -> None:
    tracker_class = getattr(runner_module, "ProcessOwnership" + "Tracker", None)
    assert tracker_class is not None
    baseline = capture_process_baseline()
    tracker = tracker_class()
    child_pid = tmp_path / "detached.pid"
    script = (
        "import os, pathlib, subprocess, sys, time; "
        "environment={'PATH': os.environ['PATH']}; "
        "child=subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(30)'], env=environment, "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, start_new_session=True); "
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid)); "
        "time.sleep(0.25)"
    )

    result = run_command(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout=10,
        environment={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYGANINI_QUALIFICATION_PROCESS_MARKER": "tracker-marker",
        },
        ownership_tracker=tracker,
    )

    assert result.exit_status == 0
    cleanup = runner_module.cleanup_temporary_processes(
        baseline,
        "tracker-marker",
        ownership_tracker=tracker,
    )
    tracked, _ = tracker.snapshot()
    assert any(pid == int(child_pid.read_text(encoding="ascii")) for pid, _ in tracked)
    assert result.process_group_cleanup == "terminated"
    assert cleanup.lingering == ()


def test_stream_write_failure_still_runs_final_cleanup_and_identity(
    git_repository: Callable[[], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repository()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pyganini"\n', encoding="ascii"
    )
    identity = capture_candidate(
        root, python_lines=("3.14",), scenario_ids=("Q001", "Q080")
    )
    identity_calls = 0
    cleanup_calls = 0

    def capture(*args: object, **kwargs: object) -> object:
        nonlocal identity_calls
        identity_calls += 1
        return identity

    def mirror(
        candidate: object, destination: Path, **kwargs: object
    ) -> CandidateMirror:
        destination.mkdir(parents=True)
        return CandidateMirror(destination, "a" * 40, identity)

    def command(command_arguments: list[str], **kwargs: object) -> CommandResult:
        distribution = Path(command_arguments[-1])
        distribution.mkdir(exist_ok=True)
        (distribution / "pyganini-test.whl").write_bytes(b"wheel")
        (distribution / "pyganini-test.tar.gz").write_bytes(b"sdist")
        return CommandResult(
            command=tuple(command_arguments),
            cwd=root,
            monotonic_start_ms=0,
            duration_ms=1,
            exit_status=0,
            stdout=b"",
            stderr=b"",
            start_error=None,
            cancelled=False,
            timed_out=False,
            output_communication_timed_out=False,
            process_group_cleanup="clean",
            process_group_cleanup_error=None,
        )

    def cleanup(*args: object, **kwargs: object) -> ProcessCleanupResult:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return ProcessCleanupResult((), (), None)

    class FailingWriter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def write_streams(self, *args: object) -> object:
            raise EvidenceError("stream denied")

        def add_scenario(self, record: object) -> None:
            pass

    def empty_baseline() -> frozenset[tuple[int, str]]:
        return frozenset()

    def empty_environment_report(**kwargs: object) -> dict[str, object]:
        return {}

    def require_no_commands(scenarios: object) -> None:
        pass

    monkeypatch.setattr(runner_module, "capture_candidate", capture)
    monkeypatch.setattr(runner_module, "capture_process_baseline", empty_baseline)
    monkeypatch.setattr(
        runner_module, "capture_environment_report", empty_environment_report
    )
    monkeypatch.setattr(runner_module, "create_candidate_mirror", mirror)
    monkeypatch.setattr(runner_module, "run_command", command)
    monkeypatch.setattr(runner_module, "cleanup_temporary_processes", cleanup)
    monkeypatch.setattr(runner_module, "EvidenceWriter", FailingWriter)
    monkeypatch.setattr(runner_module, "_require_commands", require_no_commands)

    exit_status = main(
        [
            "--pyganini-root",
            str(root),
            "--output",
            str(tmp_path / "evidence"),
            "--scenario",
            "Q001",
        ]
    )

    assert exit_status == 2
    assert cleanup_calls >= 2
    assert identity_calls == 2


def test_initial_identity_failure_still_runs_process_cleanup(
    git_repository: Callable[[], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repository()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pyganini"\n', encoding="ascii"
    )
    cleanup_calls = 0

    def failed_capture(*args: object, **kwargs: object) -> object:
        raise IdentityError("initial identity failed")

    def cleanup(*args: object, **kwargs: object) -> ProcessCleanupResult:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return ProcessCleanupResult(
            ("pid=123 ppid=1 pgid=123 start=darwin:7",), (), None
        )

    monkeypatch.setattr(runner_module, "capture_candidate", failed_capture)
    monkeypatch.setattr(runner_module, "capture_process_baseline", frozenset)
    monkeypatch.setattr(runner_module, "cleanup_temporary_processes", cleanup)

    def require_no_commands(scenarios: object) -> None:
        pass

    monkeypatch.setattr(runner_module, "_require_commands", require_no_commands)

    exit_status = main(
        [
            "--pyganini-root",
            str(root),
            "--output",
            str(tmp_path / "evidence"),
            "--scenario",
            "Q001",
        ]
    )

    assert exit_status == 2
    assert cleanup_calls == 2


def test_writer_construction_failure_cleans_root_and_recaptures_identity(
    git_repository: Callable[[], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repository()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pyganini"\n', encoding="ascii"
    )
    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    owned_root = tmp_path / "owned-temporary-root"
    identity_calls = 0
    process_cleanup_calls = 0
    temporary_instances: list[TrackedTemporaryDirectory] = []

    class TrackedTemporaryDirectory:
        name = str(owned_root)

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.cleanup_calls = 0
            temporary_instances.append(self)
            owned_root.mkdir()

        def cleanup(self) -> None:
            self.cleanup_calls += 1
            shutil.rmtree(owned_root)

    def capture(*args: object, **kwargs: object) -> object:
        nonlocal identity_calls
        identity_calls += 1
        return identity

    def cleanup(*args: object, **kwargs: object) -> ProcessCleanupResult:
        nonlocal process_cleanup_calls
        process_cleanup_calls += 1
        return ProcessCleanupResult((), (), None)

    class FailingWriter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise EvidenceError("writer construction failed")

    monkeypatch.setattr(runner_module, "capture_candidate", capture)
    monkeypatch.setattr(runner_module, "capture_process_baseline", frozenset)
    monkeypatch.setattr(runner_module, "cleanup_temporary_processes", cleanup)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", TrackedTemporaryDirectory)
    monkeypatch.setattr(runner_module, "EvidenceWriter", FailingWriter)

    def require_no_commands(scenarios: object) -> None:
        pass

    monkeypatch.setattr(runner_module, "_require_commands", require_no_commands)

    exit_status = main(
        [
            "--pyganini-root",
            str(root),
            "--output",
            str(tmp_path / "evidence"),
            "--scenario",
            "Q001",
        ]
    )

    assert exit_status == 2
    assert identity_calls == 2
    assert process_cleanup_calls >= 2
    assert temporary_instances[0].cleanup_calls == 1
    assert not owned_root.exists()


def test_final_process_audit_detects_detached_new_session_child() -> None:
    baseline = capture_process_baseline()
    marker = "detached-test-marker"
    environment = os.environ.copy()
    environment["PYGANINI_QUALIFICATION_PROCESS_MARKER"] = marker
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        survivors = temporary_processes(baseline, marker)
        assert any(f"pid={child.pid} " in survivor for survivor in survivors)
    finally:
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def test_final_process_audit_ignores_unmarked_concurrent_process() -> None:
    baseline = capture_process_baseline()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        survivors = temporary_processes(baseline, "absent-marker")
        assert all(f"pid={child.pid} " not in survivor for survivor in survivors)
    finally:
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def test_q001_uses_distribution_build_result_without_stream_misattribution(
    tmp_path: Path,
) -> None:
    build_result = run_command(
        [sys.executable, "-c", "print('distribution build')"],
        cwd=tmp_path,
        timeout=10,
        environment={"PATH": "/usr/bin:/bin"},
    )
    context = ScenarioContext(
        python=sys.executable,
        candidate_root=tmp_path,
        wheel=tmp_path / "pyganini.whl",
        temporary_root=tmp_path,
        probe_root=tmp_path,
        python_lines=("3.14",),
    )

    result = run_scenario_command(
        SCENARIOS[0],
        context,
        build_result,
        environment={"PATH": "/usr/bin:/bin"},
    )

    assert result is build_result
    assert result.command == (sys.executable, "-c", "print('distribution build')")
    assert result.stdout == b"distribution build\n"


def test_scenario_context_freezes_worker_and_fixture_source_in_candidate_mirror(
    tmp_path: Path,
) -> None:
    mirror_root = tmp_path / "candidate"
    mirror_root.mkdir()
    context = runner_module.build_scenario_context(
        candidate_root=mirror_root,
        wheel=tmp_path / "pyganini.whl",
        temporary_root=tmp_path,
        python_lines=("3.14", "3.13"),
    )

    assert context.candidate_root == mirror_root
    assert context.probe_root == mirror_root / "probes" / "qualification"


def test_validate_paths_rejects_relative_and_nested_output(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pyganini"\n', encoding="ascii"
    )
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True)

    with pytest.raises(QualificationError, match="absolute"):
        validate_paths(Path("relative"), tmp_path / "out")
    with pytest.raises(QualificationError, match="outside"):
        validate_paths(root, root / "evidence")


def test_scenario_cleanup_callback_is_invoked(tmp_path: Path) -> None:
    marker = tmp_path / "cleaned"

    def cleanup(root: Path) -> None:
        assert root == tmp_path
        marker.touch()

    scenario = Scenario("Q999", "cleanup", None, 1, (), cleanup_callback=cleanup)

    assert run_scenario_cleanup(scenario, tmp_path) is None
    assert marker.is_file()


def test_scenario_cleanup_failure_is_reported(tmp_path: Path) -> None:
    def cleanup(_: Path) -> None:
        raise OSError("cleanup failed")

    scenario = Scenario("Q999", "cleanup", None, 1, (), cleanup_callback=cleanup)

    assert run_scenario_cleanup(scenario, tmp_path) == "cleanup failed"


def test_cleanup_failure_retains_primary_infrastructure_error() -> None:
    assert combine_infrastructure_errors(
        "scenario evidence failed", "qualification cleanup failed: denied"
    ) == ("scenario evidence failed; qualification cleanup failed: denied")


def test_q080_reconciliation_converts_final_drift_to_infrastructure_error() -> None:
    record: dict[str, object] = {
        "id": "Q080",
        "status": "pass",
        "observed_outcome": "exit 0",
        "cleanup_state": "scheduled",
    }

    error = finalize_q080_record(
        record,
        identity_match=False,
        temporary_root_removed=True,
        lingering_processes=(),
        cleanup_error=None,
    )

    assert error == "candidate identity changed during qualification"
    assert record["status"] == "infrastructure_error"
    assert record["cleanup_state"] == "removed"
    assert record["final_identity_match"] is False


def test_q080_reconciliation_records_complete_cleanup() -> None:
    record: dict[str, object] = {
        "id": "Q080",
        "status": "pass",
        "observed_outcome": "exit 0",
        "cleanup_state": "scheduled",
    }

    error = finalize_q080_record(
        record,
        identity_match=True,
        temporary_root_removed=True,
        lingering_processes=(),
        cleanup_error=None,
    )

    assert error is None
    assert record["status"] == "pass"
    assert record["cleanup_state"] == "removed"
    assert record["temporary_root_removed"] is True
    assert record["lingering_processes"] == []


def test_q080_reconciliation_blocks_after_final_survivor_cleanup() -> None:
    record: dict[str, object] = {
        "id": "Q080",
        "status": "pass",
        "observed_outcome": "exit 0",
        "cleanup_state": "scheduled",
    }

    error = finalize_q080_record(
        record,
        identity_match=True,
        temporary_root_removed=True,
        lingering_processes=(),
        cleanup_error=None,
        detected_processes=("pid=123 ppid=1 pgid=123 start=start",),
    )

    assert error is not None
    assert "required final cleanup" in error
    assert record["status"] == "infrastructure_error"


def test_q080_reconciliation_blocks_on_incomplete_process_audit() -> None:
    record: dict[str, object] = {
        "id": "Q080",
        "status": "pass",
        "observed_outcome": "exit 0",
        "cleanup_state": "scheduled",
    }

    error = finalize_q080_record(
        record,
        identity_match=True,
        temporary_root_removed=True,
        lingering_processes=(),
        cleanup_error=None,
        process_audit_error="process environment unreadable",
    )

    assert error is not None
    assert "process audit failed" in error
    assert record["status"] == "infrastructure_error"


def test_candidate_report_binds_disposable_commit_to_both_identities(
    git_repository: Callable[[], Path],
) -> None:
    root = git_repository()
    initial = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    final = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))

    report = build_candidate_report(
        initial,
        final,
        disposable_commit="a" * 40,
    )

    assert report["identity_match"] is True
    assert report["initial"]["disposable_commit"] == "a" * 40
    assert report["final"]["disposable_commit"] == "a" * 40


def test_documented_runner_entrypoints_disable_live_bytecode_writes() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="ascii"
    )

    assert "python -m qualification_probes" not in readme
    assert readme.count("python -B -m qualification_probes") >= 2
