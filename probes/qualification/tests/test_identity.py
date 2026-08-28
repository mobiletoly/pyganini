from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from qualification_probes.identity import (
    IdentityError,
    capture_candidate,
    create_candidate_mirror,
)


def test_capture_records_unstaged_diff_and_sorted_untracked_manifest(
    git_repository: Callable[[], Path],
) -> None:
    root = git_repository()
    (root / "tracked.txt").write_bytes(b"changed\n")
    (root / "z.txt").write_bytes(b"z\n")
    (root / "a.txt").write_bytes(b"a\n")

    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))

    assert identity.staged == ()
    assert identity.unmerged == ()
    assert identity.diff_sha256 != "0" * 64
    assert [item.path for item in identity.untracked] == ["a.txt", "z.txt"]
    assert len(identity.combined_sha256) == 64


def test_capture_rejects_staged_content(git_repository: Callable[[], Path]) -> None:
    root = git_repository()
    (root / "staged.txt").write_bytes(b"staged\n")
    subprocess.run(["git", "-C", str(root), "add", "staged.txt"], check=True)

    with pytest.raises(IdentityError, match="staged"):
        capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))


def test_capture_rejects_candidate_symlink(git_repository: Callable[[], Path]) -> None:
    root = git_repository()
    (root / "target.txt").write_bytes(b"target\n")
    (root / "link.txt").symlink_to("target.txt")

    with pytest.raises(IdentityError, match="symlink"):
        capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))


def test_capture_rejects_unmerged_content(git_repository: Callable[[], Path]) -> None:
    root = git_repository()
    subprocess.run(["git", "-C", str(root), "switch", "-c", "other"], check=True)
    (root / "tracked.txt").write_text("other\n", encoding="ascii")
    subprocess.run(["git", "-C", str(root), "commit", "-am", "other"], check=True)
    subprocess.run(["git", "-C", str(root), "switch", "main"], check=True)
    (root / "tracked.txt").write_text("main\n", encoding="ascii")
    subprocess.run(["git", "-C", str(root), "commit", "-am", "main"], check=True)
    merged = subprocess.run(
        ["git", "-C", str(root), "merge", "other"], check=False, capture_output=True
    )
    assert merged.returncode != 0

    with pytest.raises(IdentityError, match="unmerged"):
        capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))


@pytest.mark.parametrize(
    ("arguments", "path", "label"),
    [
        (("diff", "--cached", "--name-only", "-z"), "staged.txt", "staged"),
        (
            ("diff", "--name-only", "--diff-filter=U", "-z"),
            "unmerged.txt",
            "unmerged",
        ),
    ],
)
def test_capture_rechecks_index_and_unmerged_state_at_closing_gate(
    git_repository: Callable[[], Path],
    arguments: tuple[str, ...],
    path: str,
    label: str,
) -> None:
    root = git_repository()
    matching_calls = 0

    def changing_index_runner(
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        check: bool,
        failure_label: str,
    ) -> bytes:
        nonlocal matching_calls
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            timeout=30,
        )
        if check and completed.returncode != 0:
            raise IdentityError(f"{failure_label} failed")
        if tuple(command[1:]) == arguments:
            matching_calls += 1
            if matching_calls == 2:
                return os.fsencode(path) + b"\0"
        return completed.stdout

    with pytest.raises(IdentityError, match=label):
        capture_candidate(
            root,
            python_lines=("3.14",),
            scenario_ids=("Q001",),
            command_runner=changing_index_runner,
        )


def test_recapture_detects_candidate_drift(git_repository: Callable[[], Path]) -> None:
    root = git_repository()
    initial = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    (root / "tracked.txt").write_text("drift\n", encoding="ascii")

    final = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))

    assert final.combined_sha256 != initial.combined_sha256


def test_capture_rejects_enumerated_untracked_file_disappearance(
    git_repository: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repository()
    disappearing = root / "disappearing.txt"
    disappearing.write_text("present at enumeration\n", encoding="ascii")
    original_lstat = Path.lstat
    removed = False

    def remove_before_hash(path: Path) -> object:
        nonlocal removed
        if path == disappearing and not removed:
            removed = True
            path.unlink()
            raise FileNotFoundError(path)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", remove_before_hash)

    with pytest.raises(IdentityError, match=r"changed while hashing.*disappearing"):
        capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))


def test_capture_rejects_tracked_file_reappearance_after_missing_snapshot(
    git_repository: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repository()
    tracked = root / "tracked.txt"
    tracked.unlink()
    original_lstat = Path.lstat
    restored = False

    def restore_before_hash(path: Path) -> object:
        nonlocal restored
        if path == tracked and not restored:
            restored = True
            tracked.write_text("base\n", encoding="ascii")
            raise FileNotFoundError(path)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", restore_before_hash)

    with pytest.raises(IdentityError, match="changed during identity capture"):
        capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))


def test_mirror_rejects_tracked_file_reappearance_after_capture(
    git_repository: Callable[[], Path], tmp_path: Path
) -> None:
    root = git_repository()
    tracked = root / "tracked.txt"
    tracked.unlink()
    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    tracked.write_text("base\n", encoding="ascii")

    assert identity.missing_tracked == ("tracked.txt",)
    with pytest.raises(IdentityError, match="path state changed before mirror copy"):
        create_candidate_mirror(identity, tmp_path / "mirror")


def test_identity_git_commands_accept_injected_bounded_runner(
    git_repository: Callable[[], Path],
) -> None:
    root = git_repository()
    calls: list[tuple[tuple[str, ...], Path, bool, str]] = []

    def bounded_runner(
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        check: bool,
        failure_label: str,
    ) -> bytes:
        calls.append((tuple(command), cwd, check, failure_label))
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            timeout=30,
        )
        if check and completed.returncode != 0:
            raise IdentityError(f"{failure_label} failed")
        return completed.stdout

    identity = capture_candidate(
        root,
        python_lines=("3.14",),
        scenario_ids=("Q001",),
        command_runner=bounded_runner,
    )
    mirror = create_candidate_mirror(
        identity,
        root.parent / "mirror",
        command_runner=bounded_runner,
    )

    assert calls
    assert all(cwd in {root, mirror.root} for _, cwd, _, _ in calls)
    assert any(label == "candidate Git command" for _, _, _, label in calls)
    assert any(label == "disposable Git command" for _, _, _, label in calls)


def test_identity_git_commands_inherit_process_marker(
    git_repository: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repository()
    original_run = subprocess.run
    environments: list[dict[str, str]] = []

    def record_environment(*args: object, **kwargs: object) -> object:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        checked_environment = cast(dict[object, object], environment)
        assert all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in checked_environment.items()
        )
        environments.append(cast(dict[str, str], checked_environment))
        return cast(Callable[..., object], original_run)(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record_environment)

    capture_candidate(
        root,
        python_lines=("3.14",),
        scenario_ids=("Q001",),
        environment={"PYGANINI_QUALIFICATION_PROCESS_MARKER": "identity-marker"},
    )

    assert environments
    assert all(
        environment.get("PYGANINI_QUALIFICATION_PROCESS_MARKER") == "identity-marker"
        for environment in environments
    )


def test_mirror_preserves_bytes_and_executable_mode(
    git_repository: Callable[[], Path], tmp_path: Path
) -> None:
    root = git_repository()
    executable = root / "run.sh"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (root / "ignored").mkdir()
    (root / "ignored" / "cache.bin").write_bytes(b"ignored")
    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))

    mirror = create_candidate_mirror(identity, tmp_path / "mirror")

    assert (mirror.root / "run.sh").read_bytes() == executable.read_bytes()
    assert (mirror.root / "run.sh").stat().st_mode & 0o111
    assert not (mirror.root / "ignored").exists()
    assert len(mirror.commit) == 40

    second = create_candidate_mirror(identity, tmp_path / "second-mirror")
    assert second.commit == mirror.commit


def test_mirror_rejects_executable_mode_drift_after_identity_capture(
    git_repository: Callable[[], Path], tmp_path: Path
) -> None:
    root = git_repository()
    executable = root / "run.sh"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    executable.chmod(0o644)

    with pytest.raises(IdentityError, match="mode changed before mirror copy"):
        create_candidate_mirror(identity, tmp_path / "mirror")


def test_mirror_rejects_permission_mode_drift_after_identity_capture(
    git_repository: Callable[[], Path], tmp_path: Path
) -> None:
    root = git_repository()
    source = root / "candidate.txt"
    source.write_bytes(b"same bytes\n")
    source.chmod(0o644)
    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    source.chmod(0o600)

    with pytest.raises(IdentityError, match="mode changed before mirror copy"):
        create_candidate_mirror(identity, tmp_path / "mirror")


def test_mirror_rejects_identical_atomic_replacement_after_identity_capture(
    git_repository: Callable[[], Path], tmp_path: Path
) -> None:
    root = git_repository()
    source = root / "candidate.txt"
    source.write_bytes(b"same bytes\n")
    identity = capture_candidate(root, python_lines=("3.14",), scenario_ids=("Q001",))
    replacement = root / "replacement.txt"
    replacement.write_bytes(source.read_bytes())
    replacement.chmod(source.stat().st_mode)
    replacement.replace(source)

    with pytest.raises(IdentityError, match="identity changed before mirror copy"):
        create_candidate_mirror(identity, tmp_path / "mirror")
