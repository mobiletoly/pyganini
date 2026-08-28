from __future__ import annotations

import argparse
import ctypes
import errno
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from .evidence import EvidenceError, EvidenceWriter
from .identity import (
    CandidateIdentity,
    GitCommandRunner,
    IdentityError,
    capture_candidate,
    create_candidate_mirror,
)
from .scenarios import (
    SCENARIOS,
    Scenario,
    ScenarioContext,
    ScenarioError,
    select_scenarios,
)


class QualificationError(RuntimeError):
    """Report invalid qualification input or infrastructure."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    cwd: Path
    monotonic_start_ms: int
    duration_ms: int
    exit_status: int | None
    stdout: bytes
    stderr: bytes
    start_error: str | None
    cancelled: bool
    timed_out: bool
    output_communication_timed_out: bool
    process_group_cleanup: str
    process_group_cleanup_error: str | None


ProcessEntry = tuple[int, int, int, int, str]
ProcessBaseline = frozenset[tuple[int, str]]
ProcessMonitor = tuple[threading.Event, threading.Thread, str | None]
DarwinAuditToken = tuple[int, int, int, int, int, int, int, int]


def _process_identities_by_pid(
    identities: set[tuple[int, str]] | frozenset[tuple[int, str]],
) -> dict[int, set[str]]:
    identities_by_pid: dict[int, set[str]] = {}
    for process_id, identity in identities:
        identities_by_pid.setdefault(process_id, set()).add(identity)
    return identities_by_pid


class _DarwinProcessInfo(ctypes.Structure):
    _fields_ = (
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    )


@dataclass(frozen=True, slots=True)
class ProcessCleanupResult:
    detected: tuple[str, ...]
    lingering: tuple[str, ...]
    error: str | None


class ProcessOwnershipTracker:
    """Retain exact identities of processes observed in qualification lineages."""

    def __init__(self) -> None:
        self._identities: set[tuple[int, str]] = set()
        self._errors: list[str] = []
        self._lock = threading.Lock()

    def snapshot(self) -> tuple[frozenset[tuple[int, str]], tuple[str, ...]]:
        with self._lock:
            return frozenset(self._identities), tuple(self._errors)

    def _record_error(self, error: str) -> None:
        with self._lock:
            if error not in self._errors:
                self._errors.append(error)

    def _register_root_identity(self, root_process_id: int) -> str | None:
        try:
            identity = _exact_process_identity(root_process_id)
        except QualificationError as error:
            self._record_error(str(error))
            return None
        if identity is None:
            self._record_error(
                f"process ownership root exited before capture: pid {root_process_id}"
            )
            return None
        with self._lock:
            self._identities.add((root_process_id, identity))
        return identity

    def _observe(self, root_process_id: int, root_identity: str | None) -> None:
        try:
            audit_process, rows = _process_table()
        except QualificationError as error:
            self._record_error(str(error))
            return
        with self._lock:
            identities = set(self._identities)
        identities_by_pid = _process_identities_by_pid(identities)
        matches: list[ProcessEntry] = []
        for entry in rows:
            process_id, parent_id, process_group, user_id, raw_started = entry
            if process_id != root_process_id and process_id not in identities_by_pid:
                continue
            exact = _entry_exact_identity(process_id, raw_started)
            if exact is None:
                continue
            expected = identities_by_pid.get(process_id, set())
            if process_id == root_process_id:
                if root_identity is None or exact != root_identity:
                    continue
            elif exact not in expected:
                continue
            matches.append((process_id, parent_id, process_group, user_id, exact))
        owned_processes = {entry[0] for entry in matches}
        changed = True
        while changed:
            changed = False
            for raw_entry in rows:
                if raw_entry[0] in {os.getpid(), audit_process} or any(
                    entry[0] == raw_entry[0] for entry in matches
                ):
                    continue
                if raw_entry[1] in owned_processes:
                    exact = _entry_exact_identity(raw_entry[0], raw_entry[4])
                    if exact is None:
                        continue
                    entry = (*raw_entry[:4], exact)
                    matches.append(entry)
                    owned_processes.add(entry[0])
                    changed = True
        with self._lock:
            self._identities.update((entry[0], entry[4]) for entry in matches)

    def monitor(self, root_process_id: int) -> ProcessMonitor:
        stop = threading.Event()
        root_identity = self._register_root_identity(root_process_id)

        self._observe(root_process_id, root_identity)

        def observe_until_stopped() -> None:
            while not stop.wait(0.005):
                self._observe(root_process_id, root_identity)

        thread = threading.Thread(
            target=observe_until_stopped,
            name=f"qualification-process-tracker-{root_process_id}",
            daemon=True,
        )
        thread.start()
        return stop, thread, root_identity

    def stop_monitor(
        self,
        root_process_id: int,
        monitor: ProcessMonitor,
    ) -> None:
        stop, thread, root_identity = monitor
        self._observe(root_process_id, root_identity)
        stop.set()
        thread.join(timeout=5)
        if thread.is_alive():
            self._record_error(
                f"process ownership tracker did not stop for pid {root_process_id}"
            )


def _darwin_audit_token(process_id: int) -> DarwinAuditToken | None:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    current_task = ctypes.c_uint.in_dll(libc, "mach_task_self_").value
    task_name = ctypes.c_uint()
    result = libc.task_name_for_pid(current_task, process_id, ctypes.byref(task_name))
    if result != 0:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        raise QualificationError(
            f"process identity audit failed for pid {process_id}: mach error {result}"
        )
    token = (ctypes.c_uint * 8)()
    count = ctypes.c_uint(8)
    try:
        result = libc.task_info(task_name.value, 15, token, ctypes.byref(count))
    finally:
        libc.mach_port_deallocate(current_task, task_name.value)
    if result != 0 or count.value != 8:
        raise QualificationError(
            f"process identity audit failed for pid {process_id}: mach error {result}"
        )
    values = tuple(int(value) for value in token)
    if values[5] != process_id:
        raise QualificationError(
            f"process identity audit returned mismatched pid for {process_id}"
        )
    return cast(DarwinAuditToken, values)


def _linux_process_identity(process_id: int) -> str | None:
    try:
        payload = Path(f"/proc/{process_id}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError as error:
        raise QualificationError(
            f"process identity audit failed for pid {process_id}: {error}"
        ) from error
    closing = payload.rfind(")")
    fields = payload[closing + 2 :].split() if closing >= 0 else []
    if len(fields) < 20 or not fields[19].isdigit():
        raise QualificationError(
            f"process identity audit returned malformed data for pid {process_id}"
        )
    return f"linux:{fields[19]}"


def _darwin_process_identity(process_id: int) -> str | None:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    information = _DarwinProcessInfo()
    ctypes.set_errno(0)
    result = libc.proc_pidinfo(
        process_id,
        3,
        0,
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    if result == 0:
        error_number = ctypes.get_errno()
        if error_number in {0, errno.ESRCH}:
            return None
        raise QualificationError(
            f"process identity audit failed for pid {process_id}: "
            f"{os.strerror(error_number)}"
        )
    if result != ctypes.sizeof(information) or information.pbi_pid != process_id:
        raise QualificationError(
            f"process identity audit returned malformed data for pid {process_id}"
        )
    return f"darwin:{information.pbi_start_tvsec}:{information.pbi_start_tvusec}"


def _exact_process_identity(process_id: int) -> str | None:
    if sys.platform.startswith("linux"):
        return _linux_process_identity(process_id)
    if sys.platform == "darwin":
        return _darwin_process_identity(process_id)
    raise QualificationError(f"process identity audit is unsupported on {sys.platform}")


def _entry_exact_identity(process_id: int, started: str) -> str | None:
    if started.startswith(("darwin:", "linux:")):
        return started
    return _exact_process_identity(process_id)


def _signal_process_identity(
    process: ProcessEntry, selected_signal: int
) -> tuple[bool, str | None]:
    process_id, _, _, _, expected_identity = process
    if sys.platform.startswith("linux"):
        pidfd_open = getattr(os, "pidfd_open", None)
        pidfd_signal = getattr(signal, "pidfd_send_signal", None)
        if pidfd_open is None or pidfd_signal is None:
            return False, "Linux pidfd signaling is unavailable"
        try:
            descriptor = pidfd_open(process_id)
        except ProcessLookupError:
            return False, None
        except OSError as error:
            return False, str(error)
        try:
            if _linux_process_identity(process_id) != expected_identity:
                return False, None
            pidfd_signal(descriptor, selected_signal)
        except ProcessLookupError:
            return False, None
        except OSError as error:
            return False, str(error)
        finally:
            os.close(descriptor)
        return True, None
    if sys.platform == "darwin":
        try:
            token = _darwin_audit_token(process_id)
        except QualificationError as error:
            return False, str(error)
        if token is None or _darwin_process_identity(process_id) != expected_identity:
            return False, None
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        token_buffer = (ctypes.c_uint * 8)(*token)
        ctypes.set_errno(0)
        result = libc.proc_signal_with_audittoken(
            ctypes.byref(token_buffer), selected_signal
        )
        if result != 0:
            error_number = ctypes.get_errno()
            if error_number == errno.ESRCH:
                return False, None
            return False, os.strerror(error_number)
        return True, None
    return False, f"identity-bound signaling is unsupported on {sys.platform}"


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    ownership_tracker: ProcessOwnershipTracker | None = None,
    command_marker: str | None = None,
    grace_seconds: float = 5,
) -> tuple[str, str | None]:
    try:
        _, rows = _process_table()
    except QualificationError as error:
        return "failed", str(error)
    known_owned: frozenset[tuple[int, str]] = frozenset()
    if ownership_tracker is not None:
        known_owned, _ = ownership_tracker.snapshot()
    known_by_pid = _process_identities_by_pid(known_owned)
    expected_list: list[ProcessEntry] = []
    for entry in rows:
        known_identities = known_by_pid.get(entry[0], set())
        is_marked_group_member = (
            command_marker is not None
            and entry[2] == process.pid
            and _process_has_marker(entry, command_marker)
        )
        if not known_identities and not is_marked_group_member:
            continue
        exact = _entry_exact_identity(entry[0], entry[4])
        if exact is None or (known_identities and exact not in known_identities):
            continue
        expected_list.append((*entry[:4], exact))
    expected = tuple(expected_list)
    groups: dict[int, list[ProcessEntry]] = {}
    for entry in expected:
        groups.setdefault(entry[2], []).append(entry)
    statuses: list[str] = []
    errors: list[str] = []
    for process_group, entries in sorted(groups.items()):
        status, cleanup_failure = _terminate_process_group_id(
            process_group,
            expected_processes=tuple(entries),
            grace_seconds=grace_seconds,
        )
        statuses.append(status)
        if cleanup_failure is not None:
            errors.append(f"process group {process_group}: {cleanup_failure}")
    if errors:
        return "failed", "; ".join(errors)
    if "terminated" in statuses:
        return "terminated", None
    return "clean", None


def run_command(
    command: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    timeout: float,
    environment: Mapping[str, str],
    ownership_tracker: ProcessOwnershipTracker | None = None,
) -> CommandResult:
    fixed_command = tuple(command)
    started_ns = time.monotonic_ns()
    command_tracker = ownership_tracker or ProcessOwnershipTracker()
    child_environment = dict(environment)
    child_environment.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    command_marker = secrets.token_hex(32)
    child_environment["PYGANINI_QUALIFICATION_COMMAND_MARKER"] = command_marker
    child_environment.pop("PYTHONPATH", None)
    launch_command = fixed_command
    pass_fds: tuple[int, ...] = ()
    tracker_gate: tuple[int, int] | None = None
    if ownership_tracker is not None:
        read_descriptor, write_descriptor = os.pipe()
        tracker_gate = (read_descriptor, write_descriptor)
        gate_program = (
            "import os, sys\n"
            "descriptor = int(sys.argv[1])\n"
            "if os.read(descriptor, 1) != b'1':\n"
            "    raise SystemExit(125)\n"
            "os.close(descriptor)\n"
            "os.execvpe(sys.argv[2], sys.argv[2:], os.environ)\n"
        )
        launch_command = (
            sys.executable,
            "-B",
            "-c",
            gate_program,
            str(read_descriptor),
            *fixed_command,
        )
        pass_fds = (read_descriptor,)
    try:
        process = subprocess.Popen(
            launch_command,
            cwd=cwd,
            env=child_environment,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            pass_fds=pass_fds,
        )
    except OSError as error:
        if tracker_gate is not None:
            os.close(tracker_gate[0])
            os.close(tracker_gate[1])
        duration_ms = (time.monotonic_ns() - started_ns) // 1_000_000
        return CommandResult(
            command=fixed_command,
            cwd=cwd,
            monotonic_start_ms=started_ns // 1_000_000,
            duration_ms=duration_ms,
            exit_status=None,
            stdout=b"",
            stderr=b"",
            start_error=str(error),
            cancelled=False,
            timed_out=False,
            output_communication_timed_out=False,
            process_group_cleanup="not_started",
            process_group_cleanup_error=None,
        )
    tracker_monitor: ProcessMonitor | None = None
    if tracker_gate is not None:
        os.close(tracker_gate[0])
    tracker_monitor = command_tracker.monitor(process.pid)
    if tracker_gate is not None:
        try:
            os.write(tracker_gate[1], b"1")
        finally:
            os.close(tracker_gate[1])
    cancelled = False
    timed_out = False
    output_communication_timed_out = False
    process_group_cleanup = "clean"
    process_group_cleanup_error: str | None = None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        process_group_cleanup, process_group_cleanup_error = _terminate_process_group(
            process,
            ownership_tracker=command_tracker,
            command_marker=command_marker,
        )
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as drain_error:
            output_communication_timed_out = True
            stdout = cast(bytes, drain_error.output or error.output or b"")
            stderr = drain_error.stderr or error.stderr or b""
            process_group_cleanup = "failed"
            process_group_cleanup_error = combine_infrastructure_errors(
                process_group_cleanup_error,
                "timed-out process did not close output streams after cleanup",
            )
    except KeyboardInterrupt:
        cancelled = True
        process_group_cleanup, process_group_cleanup_error = _terminate_process_group(
            process,
            ownership_tracker=command_tracker,
            command_marker=command_marker,
        )
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as error:
            output_communication_timed_out = True
            stdout = cast(bytes, error.output or b"")
            stderr = error.stderr or b""
            process_group_cleanup = "failed"
            process_group_cleanup_error = combine_infrastructure_errors(
                process_group_cleanup_error,
                "cancelled process did not close output streams after cleanup",
            )
    else:
        process_group_cleanup, process_group_cleanup_error = _terminate_process_group(
            process,
            ownership_tracker=command_tracker,
            command_marker=command_marker,
        )
    command_tracker.stop_monitor(process.pid, tracker_monitor)
    _, tracker_errors = command_tracker.snapshot()
    for tracker_error in tracker_errors:
        process_group_cleanup = "failed"
        process_group_cleanup_error = combine_infrastructure_errors(
            process_group_cleanup_error, tracker_error
        )
    duration_ms = (time.monotonic_ns() - started_ns) // 1_000_000
    return CommandResult(
        command=fixed_command,
        cwd=cwd,
        monotonic_start_ms=started_ns // 1_000_000,
        duration_ms=duration_ms,
        exit_status=process.returncode,
        stdout=stdout,
        stderr=stderr,
        start_error=None,
        cancelled=cancelled,
        timed_out=timed_out,
        output_communication_timed_out=output_communication_timed_out,
        process_group_cleanup=process_group_cleanup,
        process_group_cleanup_error=process_group_cleanup_error,
    )


def build_identity_command_runner(
    ownership_tracker: ProcessOwnershipTracker,
) -> GitCommandRunner:
    def bounded_git_command(
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        check: bool,
        failure_label: str,
    ) -> bytes:
        result = run_command(
            tuple(command),
            cwd=cwd,
            timeout=30,
            environment=environment,
            ownership_tracker=ownership_tracker,
        )
        failure: str | None = None
        if result.start_error is not None:
            failure = f"could not start: {result.start_error}"
        elif result.cancelled:
            failure = "was cancelled"
        elif result.timed_out:
            failure = "timed out"
        elif result.output_communication_timed_out:
            failure = "output communication timed out"
        elif result.process_group_cleanup == "terminated":
            failure = "detected and terminated an owned survivor"
        elif result.process_group_cleanup_error is not None:
            failure = f"cleanup failed: {result.process_group_cleanup_error}"
        elif check and result.exit_status != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            failure = f"failed ({result.exit_status}): {detail}"
        if failure is not None:
            raise IdentityError(f"{failure_label} {failure}")
        return result.stdout

    return bounded_git_command


def run_scenario_command(
    scenario: Scenario,
    context: ScenarioContext,
    build_result: CommandResult,
    *,
    environment: Mapping[str, str],
    ownership_tracker: ProcessOwnershipTracker | None = None,
) -> CommandResult:
    if scenario.id == "Q001":
        return build_result
    return run_command(
        scenario.command_builder(context, scenario.id),
        cwd=context.probe_root,
        timeout=scenario.timeout,
        environment=environment,
        ownership_tracker=ownership_tracker,
    )


def build_scenario_context(
    *,
    candidate_root: Path,
    wheel: Path,
    temporary_root: Path,
    python_lines: tuple[str, ...],
) -> ScenarioContext:
    return ScenarioContext(
        python=sys.executable,
        candidate_root=candidate_root,
        wheel=wheel,
        temporary_root=temporary_root,
        probe_root=candidate_root / "probes" / "qualification",
        python_lines=python_lines,
    )


def validate_paths(pyganini_root: Path, output: Path) -> tuple[Path, Path]:
    if not pyganini_root.is_absolute() or not output.is_absolute():
        raise QualificationError("--pyganini-root and --output must be absolute paths")
    try:
        root = pyganini_root.resolve(strict=True)
    except OSError as error:
        raise QualificationError(
            f"Pyganini root cannot be resolved: {error}"
        ) from error
    if not (root / ".git").is_dir():
        raise QualificationError(f"Pyganini root is not a Git repository: {root}")
    pyproject = root / "pyproject.toml"
    try:
        configuration = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise QualificationError(
            f"Pyganini root has invalid pyproject.toml: {error}"
        ) from error
    project = configuration.get("project")
    if not isinstance(project, dict):
        raise QualificationError("Pyganini root is missing the [project] table")
    project_configuration = cast(dict[str, object], project)
    if project_configuration.get("name") != "pyganini":
        raise QualificationError("--pyganini-root does not name the Pyganini project")
    resolved_output = output.resolve(strict=False)
    try:
        resolved_output.relative_to(root)
    except ValueError:
        pass
    else:
        raise QualificationError("--output must be outside the Pyganini root")
    if resolved_output.exists() and (
        not resolved_output.is_dir() or any(resolved_output.iterdir())
    ):
        raise QualificationError("--output must be absent or an empty directory")
    return root, resolved_output


def build_environment(
    temporary_root: Path, process_marker: str, cache_owner: str
) -> dict[str, str]:
    if not cache_owner or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for character in cache_owner
    ):
        raise QualificationError(f"invalid cache owner: {cache_owner!r}")
    cache_root = temporary_root / "caches" / cache_owner
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TMPDIR": str(temporary_root / "tmp"),
        "UV_CACHE_DIR": str(cache_root / "uv"),
        "npm_config_cache": str(cache_root / "npm"),
        "PYGANINI_QUALIFICATION_PROCESS_MARKER": process_marker,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _identity_environment(process_marker: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYGANINI_QUALIFICATION_PROCESS_MARKER": process_marker,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _tool_output(
    command: list[str],
    *,
    environment: Mapping[str, str],
    ownership_tracker: ProcessOwnershipTracker | None = None,
) -> str:
    result = run_command(
        command,
        cwd=Path(__file__).resolve().parents[1],
        timeout=30,
        environment=environment,
        ownership_tracker=ownership_tracker,
    )
    if result.timed_out:
        raise QualificationError(f"metadata command timed out: {command!r}")
    if result.cancelled:
        raise QualificationError(f"metadata command was cancelled: {command!r}")
    if result.output_communication_timed_out:
        raise QualificationError(
            f"metadata command output communication timed out: {command!r}"
        )
    if result.start_error is not None:
        raise QualificationError(
            f"metadata command could not start: {command!r}: {result.start_error}"
        )
    if result.process_group_cleanup_error is not None:
        raise QualificationError(
            "metadata command cleanup failed: "
            f"{command!r}: {result.process_group_cleanup_error}"
        )
    if result.process_group_cleanup == "terminated":
        raise QualificationError(
            f"metadata command detected and terminated an owned survivor: {command!r}"
        )
    if result.exit_status != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise QualificationError(f"prerequisite command failed: {command!r}: {detail}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def capture_environment_report(
    *,
    environment: Mapping[str, str],
    python_lines: tuple[str, ...],
    scenario_ids: tuple[str, ...],
    ownership_tracker: ProcessOwnershipTracker | None = None,
) -> dict[str, Any]:
    python_locations = {
        line: _tool_output(
            ["uv", "python", "find", line],
            environment=environment,
            ownership_tracker=ownership_tracker,
        )
        for line in python_lines
    }
    python_versions = {
        line: _tool_output(
            [location, "-VV"],
            environment=environment,
            ownership_tracker=ownership_tracker,
        )
        for line, location in python_locations.items()
    }
    return {
        "uv": _tool_output(
            ["uv", "--version"],
            environment=environment,
            ownership_tracker=ownership_tracker,
        ),
        "python_lines": list(python_lines),
        "python_versions": python_versions,
        "operating_system": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "timezone": list(time.tzname),
        "scenario_inventory": list(scenario_ids),
        "infrastructure_error": None,
        "cleanup_error": None,
    }


def _require_commands(scenarios: tuple[Scenario, ...]) -> None:
    required = {"git", "ps", "shasum", "uv"}
    if any(scenario.id == "Q070" for scenario in scenarios):
        required.update({"bash", "diff", "find", "mktemp", "node", "npm", "sort"})
    missing = sorted(command for command in required if shutil.which(command) is None)
    if missing:
        raise QualificationError(f"missing required command: {missing[0]}")


def _validate_python_selection(
    python_lines: tuple[str, ...], scenarios: tuple[Scenario, ...]
) -> None:
    supported = {"3.13", "3.14"}
    if len(python_lines) != len(set(python_lines)):
        raise QualificationError("duplicate --python line")
    unsupported = [line for line in python_lines if line not in supported]
    if unsupported:
        raise QualificationError(f"unsupported Python line: {unsupported[0]}")
    required = {
        scenario.python_line
        for scenario in scenarios
        if scenario.python_line is not None
    }
    if any(scenario.id in {"Q060", "Q070"} for scenario in scenarios):
        required.update({"3.13", "3.14"})
    missing = sorted(line for line in required if line not in python_lines)
    if missing:
        raise QualificationError(
            f"selected scenarios require omitted Python line: {missing[0]}"
        )


def _command_record(
    *,
    scenario: Scenario,
    result: CommandResult,
    status: str,
    stdout_record: dict[str, str | int],
    stderr_record: dict[str, str | int],
    temporary_root: Path,
) -> dict[str, Any]:
    if result.start_error is not None:
        observed = f"command_start_error: {result.start_error}"
    elif result.cancelled:
        observed = "cancelled"
    elif result.timed_out:
        observed = "timeout"
    else:
        observed = f"exit {result.exit_status}"
    return {
        "id": scenario.id,
        "name": scenario.name,
        "python_line": scenario.python_line,
        "command": list(result.command),
        "working_directory": str(result.cwd),
        "monotonic_start_ms": result.monotonic_start_ms,
        "duration_ms": result.duration_ms,
        "exit_status": result.exit_status,
        "command_start_error": result.start_error,
        "cancelled": result.cancelled,
        "timed_out": result.timed_out,
        "output_communication_timed_out": result.output_communication_timed_out,
        "process_group_cleanup": result.process_group_cleanup,
        "process_group_cleanup_error": result.process_group_cleanup_error,
        "expected_outcome": "accepted scenario contract passes",
        "observed_outcome": observed,
        "stdout": stdout_record,
        "stderr": stderr_record,
        "created_temporary_products": [str(temporary_root)],
        "cleanup_state": "scheduled",
        "status": status,
    }


def _skipped_record(
    *, scenario: Scenario, dependency: str, writer: EvidenceWriter
) -> dict[str, Any]:
    stdout, stderr = writer.write_streams(scenario.id, b"", b"")
    return {
        "id": scenario.id,
        "name": scenario.name,
        "python_line": scenario.python_line,
        "command": [],
        "working_directory": "<qualification-temp>",
        "monotonic_start_ms": 0,
        "duration_ms": 0,
        "exit_status": None,
        "command_start_error": None,
        "cancelled": False,
        "timed_out": False,
        "output_communication_timed_out": False,
        "process_group_cleanup": "not_started",
        "process_group_cleanup_error": None,
        "expected_outcome": "accepted scenario contract passes",
        "observed_outcome": f"skipped after dependency finding: {dependency}",
        "stdout": stdout.as_dict(),
        "stderr": stderr.as_dict(),
        "created_temporary_products": [],
        "cleanup_state": "not_started",
        "status": "finding",
    }


def run_scenario_cleanup(scenario: Scenario, temporary_root: Path) -> str | None:
    try:
        scenario.cleanup_callback(temporary_root)
    except OSError as error:
        return str(error)
    return None


def combine_infrastructure_errors(primary: str | None, cleanup: str) -> str:
    if primary is None:
        return cleanup
    return f"{primary}; {cleanup}"


def _process_table() -> tuple[int, tuple[ProcessEntry, ...]]:
    try:
        process = subprocess.Popen(
            ["ps", "-axo", "pid=,ppid=,pgid=,uid=,lstart="],
            env={**os.environ, "LANG": "C", "LC_ALL": "C"},
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise QualificationError(f"temporary-process audit failed: {error}") from error
    audit_identity_error: str | None = None
    try:
        audit_identity = _exact_process_identity(process.pid)
    except QualificationError as error:
        audit_identity = None
        audit_identity_error = str(error)
    try:
        audit_group = os.getpgid(process.pid)
    except ProcessLookupError:
        audit_group = process.pid
    audit_entry = (
        (
            process.pid,
            os.getpid(),
            audit_group,
            os.getuid(),
            audit_identity,
        )
        if audit_identity is not None
        else None
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired as error:
        cleanup_error: str | None = None
        if audit_entry is None:
            cleanup_error = (
                audit_identity_error or "audit process identity was unavailable"
            )
        else:
            _, cleanup_error = _signal_process_identity(audit_entry, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.communicate(timeout=5)
        detail = "temporary-process audit timed out"
        if cleanup_error is not None:
            detail += f"; identity-bound cleanup failed: {cleanup_error}"
        raise QualificationError(detail) from error
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise QualificationError(f"temporary-process audit failed: {detail}")
    rows: list[ProcessEntry] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        fields = line.strip().split(maxsplit=4)
        if len(fields) != 5:
            raise QualificationError(
                f"temporary-process audit found malformed process table row: {line!r}"
            )
        try:
            process_id = int(fields[0])
            parent_id = int(fields[1])
            process_group = int(fields[2])
            user_id = int(fields[3])
        except ValueError as error:
            raise QualificationError(
                f"temporary-process audit found malformed process table row: {line!r}"
            ) from error
        if process_id <= 0 or parent_id < 0 or process_group <= 0:
            raise QualificationError(
                f"temporary-process audit found malformed process table row: {line!r}"
            )
        rows.append((process_id, parent_id, process_group, user_id, fields[4]))
    return process.pid, tuple(rows)


def capture_process_baseline() -> ProcessBaseline:
    _, rows = _process_table()
    identities: set[tuple[int, str]] = set()
    for process_id, _, _, user_id, started in rows:
        if user_id == os.getuid():
            exact = _entry_exact_identity(process_id, started)
            if exact is None:
                continue
            started = exact
        identities.add((process_id, started))
    return frozenset(identities)


def _process_environment(process_id: int) -> bytes | None:
    if sys.platform.startswith("linux"):
        try:
            return Path(f"/proc/{process_id}/environ").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            return None
        except PermissionError as error:
            raise QualificationError(
                f"process environment audit failed for pid {process_id}: {error}"
            ) from error
        except OSError as error:
            raise QualificationError(
                f"process environment audit failed for pid {process_id}: {error}"
            ) from error
    if sys.platform == "darwin":
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, process_id)
        size = ctypes.c_size_t()
        ctypes.set_errno(0)
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            error_number = ctypes.get_errno()
            if error_number == errno.ESRCH:
                return None
            raise QualificationError(
                "process environment audit failed for pid "
                f"{process_id}: {os.strerror(error_number)}"
            )
        if size.value < ctypes.sizeof(ctypes.c_int) or size.value > 16 * 1024 * 1024:
            raise QualificationError(
                f"process environment audit returned invalid size for pid {process_id}"
            )
        buffer = ctypes.create_string_buffer(size.value)
        ctypes.set_errno(0)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            error_number = ctypes.get_errno()
            if error_number == errno.ESRCH:
                return None
            raise QualificationError(
                "process environment audit failed for pid "
                f"{process_id}: {os.strerror(error_number)}"
            )
        return buffer.raw[: size.value]
    raise QualificationError(
        f"process environment audit is unsupported on {sys.platform}"
    )


def _process_environment_entries(process_id: int, payload: bytes) -> tuple[bytes, ...]:
    if sys.platform.startswith("linux"):
        entries = tuple(entry for entry in payload.split(b"\0") if entry)
    elif sys.platform == "darwin":
        integer_size = ctypes.sizeof(ctypes.c_int)
        if len(payload) < integer_size:
            raise QualificationError(
                "process environment audit returned malformed data for pid "
                f"{process_id}"
            )
        argument_count = int.from_bytes(
            payload[:integer_size], byteorder=sys.byteorder, signed=True
        )
        if argument_count < 0 or argument_count > 1_000_000:
            raise QualificationError(
                "process environment audit returned malformed data for pid "
                f"{process_id}"
            )
        offset = integer_size

        def consume_string() -> bytes:
            nonlocal offset
            end = payload.find(b"\0", offset)
            if end < 0:
                raise QualificationError(
                    "process environment audit returned malformed data for pid "
                    f"{process_id}"
                )
            value = payload[offset:end]
            offset = end + 1
            return value

        consume_string()
        while offset < len(payload) and payload[offset] == 0:
            offset += 1
        for _ in range(argument_count):
            consume_string()
        entries = tuple(entry for entry in payload[offset:].split(b"\0") if entry)
    else:
        raise QualificationError(
            f"process environment audit is unsupported on {sys.platform}"
        )
    if any(b"=" not in entry or entry.startswith(b"=") for entry in entries):
        raise QualificationError(
            f"process environment audit returned malformed data for pid {process_id}"
        )
    return entries


def _process_has_marker(entry: ProcessEntry, command_marker: str) -> bool:
    process_id = entry[0]
    expected_identity = _entry_exact_identity(process_id, entry[4])
    if expected_identity is None:
        return False
    try:
        payload = _process_environment(process_id)
        if payload is None:
            return False
        entries = _process_environment_entries(process_id, payload)
    except QualificationError:
        return False
    if _exact_process_identity(process_id) != expected_identity:
        return False
    marker = f"PYGANINI_QUALIFICATION_COMMAND_MARKER={command_marker}".encode("ascii")
    return marker in entries


def _describe_process(entry: ProcessEntry) -> str:
    process_id, parent_id, process_group, _, started = entry
    return f"pid={process_id} ppid={parent_id} pgid={process_group} start={started}"


def _audit_temporary_processes(
    baseline: ProcessBaseline,
    process_marker: str,
    *,
    known_owned: frozenset[tuple[int, str]] = frozenset(),
) -> tuple[tuple[ProcessEntry, ...], tuple[str, ...]]:
    audit_process, rows = _process_table()
    marker = f"PYGANINI_QUALIFICATION_PROCESS_MARKER={process_marker}".encode("ascii")
    marker_prefix = b"PYGANINI_QUALIFICATION_PROCESS_MARKER="
    matches: list[ProcessEntry] = []
    errors: list[str] = []
    current_user = os.getuid()
    eligible: list[tuple[ProcessEntry, tuple[bytes, ...]]] = []
    for raw_entry in rows:
        process_id, parent_id, process_group, user_id, started = raw_entry
        if user_id == current_user:
            exact = _entry_exact_identity(process_id, started)
            if exact is None:
                continue
            started = exact
        entry = (process_id, parent_id, process_group, user_id, started)
        if (
            (process_id, started) in baseline
            or process_id in {os.getpid(), audit_process}
            or user_id != current_user
        ):
            continue
        is_known_owned = (process_id, started) in known_owned
        if is_known_owned:
            matches.append(entry)
        try:
            environment = _process_environment(process_id)
            if environment is None:
                continue
            entries = _process_environment_entries(process_id, environment)
        except QualificationError as error:
            errors.append(str(error))
            if is_known_owned:
                eligible.append((entry, ()))
            continue
        marker_entries = tuple(
            entry for entry in entries if entry.startswith(marker_prefix)
        )
        if marker_entries and marker not in marker_entries:
            errors.append(
                "process environment audit found a replaced marker for pid "
                f"{process_id}"
            )
            continue
        eligible.append((entry, entries))
        if marker in entries and entry not in matches:
            matches.append(entry)

    owned_processes = {entry[0] for entry in matches}
    changed = True
    while changed:
        changed = False
        for entry, _ in eligible:
            if entry in matches:
                continue
            if entry[1] in owned_processes:
                matches.append(entry)
                owned_processes.add(entry[0])
                changed = True
    for entry, entries in eligible:
        if entry in matches and not entries and (entry[0], entry[4]) not in known_owned:
            errors.append(
                "process environment audit found an empty environment for owned pid "
                f"{entry[0]}"
            )
    return tuple(matches), tuple(errors)


def temporary_processes(
    baseline: ProcessBaseline, process_marker: str
) -> tuple[str, ...]:
    matches, errors = _audit_temporary_processes(baseline, process_marker)
    if errors:
        raise QualificationError("; ".join(errors))
    return tuple(_describe_process(entry) for entry in matches)


def _terminate_process_group_id(
    process_group: int,
    *,
    expected_processes: tuple[ProcessEntry, ...],
    grace_seconds: float = 5,
) -> tuple[str, str | None]:
    if process_group == os.getpgrp():
        return (
            "failed",
            f"refused to terminate qualification process group {process_group}",
        )
    selected = tuple(entry for entry in expected_processes if entry[2] == process_group)
    if not selected:
        return "clean", None
    signalled = False
    errors: list[str] = []
    for entry in sorted(selected, key=lambda item: item[0], reverse=True):
        sent, error = _signal_process_identity(entry, signal.SIGTERM)
        signalled = signalled or sent
        if error is not None:
            errors.append(f"pid {entry[0]}: {error}")
    if errors:
        return "failed", "; ".join(errors)
    if not signalled:
        return "clean", None
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        alive = _owned_processes_alive(selected)
        if not alive:
            return "terminated", None
        time.sleep(0.01)
    alive = _owned_processes_alive(selected)
    errors = []
    for entry in alive:
        _, error = _signal_process_identity(entry, signal.SIGKILL)
        if error is not None:
            errors.append(f"pid {entry[0]}: {error}")
    if errors:
        return "failed", "; ".join(errors)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not _owned_processes_alive(selected):
            return "terminated", None
        time.sleep(0.01)
    survivors = _owned_processes_alive(selected)
    return "failed", "owned processes survived SIGKILL: " + ", ".join(
        str(entry[0]) for entry in survivors
    )


def _owned_processes_alive(
    expected_processes: tuple[ProcessEntry, ...],
) -> tuple[ProcessEntry, ...]:
    expected = {(entry[0], entry[4]) for entry in expected_processes}
    try:
        _, rows = _process_table()
    except QualificationError:
        return expected_processes
    alive: list[ProcessEntry] = []
    expected_by_pid = _process_identities_by_pid(expected)
    for entry in rows:
        expected_identities = expected_by_pid.get(entry[0], set())
        if not expected_identities:
            continue
        exact = _entry_exact_identity(entry[0], entry[4])
        if exact is not None and exact in expected_identities:
            alive.append((*entry[:4], exact))
    return tuple(alive)


def cleanup_temporary_processes(
    baseline: ProcessBaseline,
    process_marker: str,
    *,
    ownership_tracker: ProcessOwnershipTracker | None = None,
) -> ProcessCleanupResult:
    known_owned: frozenset[tuple[int, str]] = frozenset()
    tracker_errors: tuple[str, ...] = ()
    if ownership_tracker is not None:
        known_owned, tracker_errors = ownership_tracker.snapshot()
    try:
        detected, audit_errors = _audit_temporary_processes(
            baseline,
            process_marker,
            known_owned=known_owned,
        )
    except QualificationError as error:
        return ProcessCleanupResult((), (), str(error))
    cleanup_errors = [*tracker_errors, *audit_errors]
    for process_group in sorted({entry[2] for entry in detected}):
        _, cleanup_failure = _terminate_process_group_id(
            process_group,
            expected_processes=tuple(
                entry for entry in detected if entry[2] == process_group
            ),
        )
        if cleanup_failure is not None:
            cleanup_errors.append(
                f"process group {process_group} cleanup failed: {cleanup_failure}"
            )
    try:
        lingering, final_audit_errors = _audit_temporary_processes(
            baseline,
            process_marker,
            known_owned=known_owned,
        )
    except QualificationError as error:
        lingering = detected
        cleanup_errors.append(str(error))
    else:
        cleanup_errors.extend(final_audit_errors)
    return ProcessCleanupResult(
        detected=tuple(_describe_process(entry) for entry in detected),
        lingering=tuple(_describe_process(entry) for entry in lingering),
        error="; ".join(cleanup_errors) if cleanup_errors else None,
    )


def finalize_q080_record(
    record: dict[str, Any],
    *,
    identity_match: bool,
    temporary_root_removed: bool,
    lingering_processes: tuple[str, ...],
    cleanup_error: str | None,
    detected_processes: tuple[str, ...] = (),
    process_audit_error: str | None = None,
) -> str | None:
    errors: list[str] = []
    if not identity_match:
        errors.append("candidate identity changed during qualification")
    if cleanup_error is not None:
        errors.append(f"qualification cleanup failed: {cleanup_error}")
    elif not temporary_root_removed:
        errors.append("qualification temporary root remains after cleanup")
    if lingering_processes:
        errors.append(
            "qualification processes survived scenario cleanup: "
            + "; ".join(lingering_processes)
        )
    elif detected_processes:
        errors.append(
            "qualification processes required final cleanup: "
            + "; ".join(detected_processes)
        )
    if process_audit_error is not None:
        errors.append(f"qualification process audit failed: {process_audit_error}")
    if record.get("status") == "infrastructure_error":
        errors.append("Q080 mirror audit is incomplete")
    record["final_identity_match"] = identity_match
    record["temporary_root_removed"] = temporary_root_removed
    record["lingering_processes"] = list(lingering_processes)
    record["detected_processes"] = list(detected_processes)
    record["process_audit_error"] = process_audit_error
    record["cleanup_state"] = (
        "removed" if temporary_root_removed and cleanup_error is None else "failed"
    )
    if errors:
        error = "; ".join(errors)
        record["status"] = "infrastructure_error"
        record["observed_outcome"] = error
        return error
    return None


def _identity_report(identity: CandidateIdentity) -> dict[str, Any]:
    return identity.as_dict()


def build_candidate_report(
    initial: CandidateIdentity,
    final: CandidateIdentity | None,
    *,
    disposable_commit: str | None,
) -> dict[str, Any]:
    initial_with_commit = replace(initial, disposable_commit=disposable_commit)
    final_with_commit = (
        replace(final, disposable_commit=disposable_commit)
        if final is not None
        else None
    )
    return {
        "initial": _identity_report(initial_with_commit),
        "final": (
            _identity_report(final_with_commit)
            if final_with_commit is not None
            else None
        ),
        "identity_match": (
            final_with_commit is not None
            and initial_with_commit.combined_sha256 == final_with_commit.combined_sha256
        ),
    }


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run repository-internal functional qualification against one identified "
            "Pyganini candidate."
        )
    )
    parser.add_argument("--pyganini-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", action="append", dest="python_lines")
    parser.add_argument("--scenario", action="append", dest="scenario_ids")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    parsed = _parse_args(arguments)
    python_lines = tuple(parsed.python_lines or ("3.14", "3.13"))
    filters = tuple(parsed.scenario_ids or ())
    try:
        pyganini_root, output = validate_paths(parsed.pyganini_root, parsed.output)
        scenarios = select_scenarios(filters, SCENARIOS)
        _validate_python_selection(python_lines, scenarios)
        _require_commands(scenarios)
        process_baseline = capture_process_baseline()
    except (OSError, QualificationError, ScenarioError) as error:
        print(f"qualification input error: {error}", file=sys.stderr)
        return 2

    initial: CandidateIdentity | None = None
    final: CandidateIdentity | None = None
    writer: EvidenceWriter | None = None
    records: list[dict[str, Any]] = []
    scenario_status: dict[str, str] = {}
    verdict = "BLOCKED_EVIDENCE_INCOMPLETE"
    infrastructure_error: str | None = None
    evidence_error: str | None = None
    cleanup_error: str | None = None
    build_result: CommandResult | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    temporary_path: Path | None = None
    disposable_commit: str | None = None
    detected_processes: tuple[str, ...] = ()
    lingering_processes: tuple[str, ...] = ()
    process_audit_error: str | None = None
    environment_report: dict[str, Any] | None = None
    process_marker = secrets.token_hex(32)
    ownership_tracker = ProcessOwnershipTracker()
    identity_command_runner = build_identity_command_runner(ownership_tracker)
    selected_ids = tuple(scenario.id for scenario in scenarios)
    identity_environment = _identity_environment(process_marker)

    try:
        initial = capture_candidate(
            pyganini_root,
            python_lines=python_lines,
            scenario_ids=selected_ids,
            environment=identity_environment,
            command_runner=identity_command_runner,
        )
        temporary = tempfile.TemporaryDirectory(prefix="pyganini-qualification-")
        temporary_path = Path(temporary.name)
        (temporary_path / "tmp").mkdir()
        writer = EvidenceWriter(
            output, temporary_root=temporary_path, pyganini_root=pyganini_root
        )
        metadata_environment = build_environment(
            temporary_path, process_marker, "metadata"
        )
        q001_environment = build_environment(temporary_path, process_marker, "Q001")
        try:
            environment_report = capture_environment_report(
                environment=metadata_environment,
                python_lines=python_lines,
                scenario_ids=selected_ids,
                ownership_tracker=ownership_tracker,
            )
            mirror = create_candidate_mirror(
                initial,
                temporary_path / "candidate",
                environment=q001_environment,
                command_runner=identity_command_runner,
            )
            initial = mirror.identity
            disposable_commit = mirror.commit
            distribution = temporary_path / "distribution"
            distribution.mkdir()
            build_result = run_command(
                ["uv", "build", "--out-dir", str(distribution)],
                cwd=mirror.root,
                timeout=900,
                environment=q001_environment,
                ownership_tracker=ownership_tracker,
            )
            if (
                build_result.start_error is not None
                or build_result.cancelled
                or build_result.timed_out
                or build_result.exit_status != 0
                or build_result.process_group_cleanup == "terminated"
                or build_result.process_group_cleanup_error is not None
            ):
                infrastructure_error = "candidate distribution build failed"
            wheels = tuple(distribution.glob("pyganini-*.whl"))
            sdists = tuple(distribution.glob("pyganini-*.tar.gz"))
            if infrastructure_error is None and (len(wheels) != 1 or len(sdists) != 1):
                infrastructure_error = (
                    "candidate build did not produce one wheel and one source "
                    "distribution"
                )
            wheel = wheels[0] if len(wheels) == 1 else distribution / "missing.whl"
            context = build_scenario_context(
                candidate_root=mirror.root,
                wheel=wheel,
                temporary_root=temporary_path,
                python_lines=python_lines,
            )
            if infrastructure_error is None:
                for scenario in scenarios:
                    failed_dependency = next(
                        (
                            dependency
                            for dependency in scenario.dependencies
                            if scenario_status.get(dependency) == "finding"
                        ),
                        None,
                    )
                    if failed_dependency is not None:
                        print(
                            f"[{scenario.id}] skipped after dependency finding "
                            f"{failed_dependency}",
                            flush=True,
                        )
                        record = _skipped_record(
                            scenario=scenario,
                            dependency=failed_dependency,
                            writer=writer,
                        )
                        records.append(record)
                        writer.add_scenario(record)
                        scenario_status[scenario.id] = "finding"
                        continue
                    print(f"[{scenario.id}] start: {scenario.name}", flush=True)
                    result = run_scenario_command(
                        scenario,
                        context,
                        build_result,
                        environment=build_environment(
                            temporary_path, process_marker, scenario.id
                        ),
                        ownership_tracker=ownership_tracker,
                    )
                    scenario_cleanup_error = run_scenario_cleanup(
                        scenario, temporary_path
                    )
                    stdout_record, stderr_record = writer.write_streams(
                        scenario.id, result.stdout, result.stderr
                    )
                    status = scenario.expected_outcome_evaluator(result)
                    if scenario_cleanup_error is not None:
                        status = "infrastructure_error"
                        infrastructure_error = (
                            f"{scenario.id} cleanup failed: {scenario_cleanup_error}"
                        )
                    record = _command_record(
                        scenario=scenario,
                        result=result,
                        status=status,
                        stdout_record=stdout_record.as_dict(),
                        stderr_record=stderr_record.as_dict(),
                        temporary_root=temporary_path,
                    )
                    if scenario_cleanup_error is not None:
                        record["cleanup_state"] = "failed"
                        record["observed_outcome"] = (
                            f"scenario cleanup failed: {scenario_cleanup_error}"
                        )
                    records.append(record)
                    writer.add_scenario(record)
                    scenario_status[scenario.id] = status
                    print(
                        f"[{scenario.id}] {status}: {record['observed_outcome']}",
                        flush=True,
                    )
                    if status == "infrastructure_error":
                        infrastructure_error = combine_infrastructure_errors(
                            infrastructure_error,
                            f"{scenario.id} evidence is incomplete",
                        )
                        break
            else:
                assert build_result is not None
                stdout_record, stderr_record = writer.write_streams(
                    "Q001", build_result.stdout, build_result.stderr
                )
                q001 = SCENARIOS[0]
                record = _command_record(
                    scenario=q001,
                    result=build_result,
                    status="infrastructure_error",
                    stdout_record=stdout_record.as_dict(),
                    stderr_record=stderr_record.as_dict(),
                    temporary_root=temporary_path,
                )
                records.append(record)
                writer.add_scenario(record)
                scenario_status["Q001"] = "infrastructure_error"
        except EvidenceError as error:
            evidence_error = str(error)
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, evidence_error
            )
        except (IdentityError, OSError, QualificationError) as error:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, str(error)
            )
        finally:
            process_cleanup = cleanup_temporary_processes(
                process_baseline,
                process_marker,
                ownership_tracker=ownership_tracker,
            )
            detected_processes = process_cleanup.detected
            lingering_processes = process_cleanup.lingering
            if process_cleanup.error is not None:
                process_audit_error = combine_infrastructure_errors(
                    process_audit_error, process_cleanup.error
                )
                infrastructure_error = combine_infrastructure_errors(
                    infrastructure_error, process_cleanup.error
                )
            if detected_processes:
                infrastructure_error = combine_infrastructure_errors(
                    infrastructure_error,
                    "qualification processes survived scenario cleanup and required "
                    "final termination",
                )
            assert temporary is not None
            try:
                temporary.cleanup()
            except OSError as error:
                cleanup_error = str(error)
        try:
            captured_final = capture_candidate(
                pyganini_root,
                python_lines=python_lines,
                scenario_ids=selected_ids,
                environment=identity_environment,
                command_runner=identity_command_runner,
            )
            final = replace(
                captured_final,
                disposable_commit=disposable_commit,
            )
        except (IdentityError, OSError) as error:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, f"final candidate identity failed: {error}"
            )
        final_process_cleanup = cleanup_temporary_processes(
            process_baseline,
            process_marker,
            ownership_tracker=ownership_tracker,
        )
        new_detected_processes = tuple(
            process
            for process in final_process_cleanup.detected
            if process not in detected_processes
        )
        detected_processes += new_detected_processes
        lingering_processes = final_process_cleanup.lingering
        if final_process_cleanup.error is not None:
            process_audit_error = combine_infrastructure_errors(
                process_audit_error, final_process_cleanup.error
            )
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, final_process_cleanup.error
            )
        if new_detected_processes:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error,
                "qualification processes survived final identity capture and "
                "required termination",
            )
        identity_match = (
            final is not None and initial.combined_sha256 == final.combined_sha256
        )
        temporary_root_removed = not temporary_path.exists()
        final_gate_errors: list[str] = []
        if not identity_match:
            final_gate_errors.append("candidate identity changed during qualification")
        if cleanup_error is not None:
            final_gate_errors.append(f"qualification cleanup failed: {cleanup_error}")
        elif not temporary_root_removed:
            final_gate_errors.append(
                "qualification temporary root remains after cleanup"
            )
        if lingering_processes:
            final_gate_errors.append(
                "qualification processes survived final cleanup: "
                + "; ".join(lingering_processes)
            )
        if final_gate_errors:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, "; ".join(final_gate_errors)
            )
        for record in records:
            if record["id"] == "Q080":
                q080_error = finalize_q080_record(
                    record,
                    identity_match=identity_match,
                    temporary_root_removed=temporary_root_removed,
                    lingering_processes=lingering_processes,
                    cleanup_error=cleanup_error,
                    detected_processes=detected_processes,
                    process_audit_error=process_audit_error,
                )
                scenario_status["Q080"] = str(record["status"])
                if q080_error is not None and not final_gate_errors:
                    infrastructure_error = combine_infrastructure_errors(
                        infrastructure_error, q080_error
                    )
            elif record["cleanup_state"] == "scheduled":
                record["cleanup_state"] = (
                    "removed"
                    if temporary_root_removed and cleanup_error is None
                    else "failed"
                )
        if infrastructure_error is None:
            verdict = (
                "FINDINGS_REQUIRE_REMEDIATION"
                if any(status == "finding" for status in scenario_status.values())
                else "PASS_TO_PERFORMANCE_QUALIFICATION"
            )
    except EvidenceError as error:
        evidence_error = str(error)
        infrastructure_error = combine_infrastructure_errors(
            infrastructure_error, evidence_error
        )
    except (IdentityError, OSError, QualificationError) as error:
        infrastructure_error = str(error)

    if writer is None or initial is None or temporary_path is None:
        failed_initial_cleanup = cleanup_temporary_processes(
            process_baseline,
            process_marker,
            ownership_tracker=ownership_tracker,
        )
        if failed_initial_cleanup.error is not None:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, failed_initial_cleanup.error
            )
        if failed_initial_cleanup.detected:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error,
                "qualification processes survived failed initialization and "
                "required termination",
            )
        if failed_initial_cleanup.lingering:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error,
                "qualification processes survived failed-initialization cleanup: "
                + "; ".join(failed_initial_cleanup.lingering),
            )
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError as error:
                infrastructure_error = combine_infrastructure_errors(
                    infrastructure_error,
                    f"qualification temporary-root cleanup failed: {error}",
                )
            if temporary_path is not None and temporary_path.exists():
                infrastructure_error = combine_infrastructure_errors(
                    infrastructure_error,
                    "qualification temporary root remains after failed initialization",
                )
        if initial is not None:
            try:
                captured_final = capture_candidate(
                    pyganini_root,
                    python_lines=python_lines,
                    scenario_ids=selected_ids,
                    environment=identity_environment,
                    command_runner=identity_command_runner,
                )
                final = replace(
                    captured_final,
                    disposable_commit=disposable_commit,
                )
                if initial.combined_sha256 != final.combined_sha256:
                    infrastructure_error = combine_infrastructure_errors(
                        infrastructure_error,
                        "candidate identity changed during failed initialization",
                    )
            except (IdentityError, OSError) as error:
                infrastructure_error = combine_infrastructure_errors(
                    infrastructure_error,
                    f"final candidate identity failed: {error}",
                )
        failed_final_cleanup = cleanup_temporary_processes(
            process_baseline,
            process_marker,
            ownership_tracker=ownership_tracker,
        )
        if failed_final_cleanup.error is not None:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error, failed_final_cleanup.error
            )
        if failed_final_cleanup.detected:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error,
                "qualification processes survived failed-initialization final "
                "identity capture and required termination",
            )
        if failed_final_cleanup.lingering:
            infrastructure_error = combine_infrastructure_errors(
                infrastructure_error,
                "qualification processes survived failed-initialization final "
                "cleanup: " + "; ".join(failed_final_cleanup.lingering),
            )
        print(
            f"BLOCKED_EVIDENCE_INCOMPLETE: {infrastructure_error or 'identity failed'}",
            file=sys.stderr,
        )
        return 2
    if evidence_error is not None:
        print(
            f"BLOCKED_EVIDENCE_INCOMPLETE: {infrastructure_error or evidence_error}",
            file=sys.stderr,
        )
        return 2

    if environment_report is None:
        environment_report = {
            "python_lines": list(python_lines),
            "operating_system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "timezone": list(time.tzname),
            "scenario_inventory": list(selected_ids),
        }
    environment_report["infrastructure_error"] = infrastructure_error
    environment_report["cleanup_error"] = cleanup_error
    candidate_report = build_candidate_report(
        initial,
        final,
        disposable_commit=disposable_commit,
    )
    if infrastructure_error is not None:
        verdict = "BLOCKED_EVIDENCE_INCOMPLETE"
    try:
        writer.finalize(
            candidate=candidate_report,
            environment=environment_report,
            verdict=verdict,
        )
    except (EvidenceError, OSError) as error:
        print(f"BLOCKED_EVIDENCE_INCOMPLETE: {error}", file=sys.stderr)
        return 2
    print(verdict, flush=True)
    if verdict == "PASS_TO_PERFORMANCE_QUALIFICATION":
        return 0
    if verdict == "FINDINGS_REQUIRE_REMEDIATION":
        return 1
    return 2
