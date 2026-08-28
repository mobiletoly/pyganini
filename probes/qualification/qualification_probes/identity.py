from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol


class IdentityError(RuntimeError):
    """Report candidate identity or mirror construction failure."""


class GitCommandRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        check: bool,
        failure_label: str,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    size: int
    sha256: str
    mode: int
    executable: bool
    device: int
    inode: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    root: Path
    branch: str
    head: str
    upstream: str | None
    ahead: int | None
    behind: int | None
    porcelain_v2: str
    staged: tuple[str, ...]
    unmerged: tuple[str, ...]
    missing_tracked: tuple[str, ...]
    diff_sha256: str
    untracked: tuple[FileRecord, ...]
    files: tuple[FileRecord, ...]
    combined_sha256: str
    runner_sha256: str
    python_lines: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    disposable_commit: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["root"] = str(self.root)
        return data


@dataclass(frozen=True, slots=True)
class CandidateMirror:
    root: Path
    commit: str
    identity: CandidateIdentity


def _git(
    root: Path,
    arguments: list[str],
    *,
    check: bool = True,
    environment: Mapping[str, str] | None = None,
    command_runner: GitCommandRunner | None = None,
) -> bytes:
    selected_environment = os.environ.copy()
    if environment is not None:
        selected_environment.update(environment)
    selected_environment["LC_ALL"] = "C"
    selected_environment["LANG"] = "C"
    runner = command_runner or _default_git_command_runner
    return runner(
        ("git", *arguments),
        cwd=root,
        environment=selected_environment,
        check=check,
        failure_label="candidate Git command",
    )


def _default_git_command_runner(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    check: bool,
    failure_label: str,
) -> bytes:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise IdentityError(f"{failure_label} timed out") from error
    except OSError as error:
        raise IdentityError(f"{failure_label} could not start: {error}") from error
    if check and completed.returncode != 0:
        raise IdentityError(
            f"{failure_label} failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed.stdout


def _nul_paths(payload: bytes) -> tuple[str, ...]:
    values = [os.fsdecode(value) for value in payload.split(b"\0") if value]
    return tuple(sorted(values, key=os.fsencode))


def _hash_regular_file(
    root: Path, relative: str, *, allow_missing: bool = False
) -> FileRecord | None:
    path = root / relative
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        if allow_missing:
            return None
        raise IdentityError(
            f"candidate file changed while hashing: {relative}"
        ) from error
    except OSError as error:
        raise IdentityError(
            f"candidate file is unreadable: {relative}: {error}"
        ) from error
    if stat.S_ISLNK(before.st_mode):
        raise IdentityError(f"candidate symlink is forbidden: {relative}")
    if not stat.S_ISREG(before.st_mode):
        raise IdentityError(f"candidate special file is forbidden: {relative}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        after = path.lstat()
    except FileNotFoundError as error:
        raise IdentityError(
            f"candidate file changed while hashing: {relative}"
        ) from error
    except OSError as error:
        raise IdentityError(
            f"candidate file is unreadable: {relative}: {error}"
        ) from error
    stable_fields = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    final_fields = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if stable_fields != final_fields:
        raise IdentityError(f"candidate file changed while hashing: {relative}")
    return FileRecord(
        path=relative,
        size=before.st_size,
        sha256=digest.hexdigest(),
        mode=stat.S_IMODE(before.st_mode),
        executable=bool(before.st_mode & 0o111),
        device=before.st_dev,
        inode=before.st_ino,
        mtime_ns=before.st_mtime_ns,
    )


def _runner_hash(runner_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        runner_root.glob("*.py"), key=lambda item: os.fsencode(item.name)
    ):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_verified_file(root: Path, record: FileRecord) -> bytes:
    path = root / record.path
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise IdentityError(
            f"candidate changed before mirror copy: {record.path}"
        ) from error
    except OSError as error:
        raise IdentityError(
            f"candidate file is unreadable before mirror copy: {record.path}: {error}"
        ) from error
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise IdentityError(
            f"candidate file type changed before mirror copy: {record.path}"
        )
    if (
        before.st_dev != record.device
        or before.st_ino != record.inode
        or before.st_mtime_ns != record.mtime_ns
    ):
        raise IdentityError(
            f"candidate identity changed before mirror copy: {record.path}"
        )
    if stat.S_IMODE(before.st_mode) != record.mode:
        raise IdentityError(f"candidate mode changed before mirror copy: {record.path}")
    try:
        data = path.read_bytes()
        after = path.lstat()
    except FileNotFoundError as error:
        raise IdentityError(
            f"candidate changed before mirror copy: {record.path}"
        ) from error
    except OSError as error:
        raise IdentityError(
            f"candidate file is unreadable before mirror copy: {record.path}: {error}"
        ) from error
    stable_fields = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    final_fields = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if stable_fields != final_fields:
        raise IdentityError(f"candidate changed before mirror copy: {record.path}")
    if len(data) != record.size or hashlib.sha256(data).hexdigest() != record.sha256:
        raise IdentityError(f"candidate changed before mirror copy: {record.path}")
    return data


def capture_candidate(
    root: Path,
    *,
    python_lines: tuple[str, ...],
    scenario_ids: tuple[str, ...],
    runner_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    command_runner: GitCommandRunner | None = None,
) -> CandidateIdentity:
    resolved = root.resolve(strict=True)
    if not (resolved / ".git").exists():
        raise IdentityError(f"candidate is not a Git repository: {resolved}")

    def candidate_git(arguments: list[str], *, check: bool = True) -> bytes:
        return _git(
            resolved,
            arguments,
            check=check,
            environment=environment,
            command_runner=command_runner,
        )

    unmerged = _nul_paths(
        candidate_git(["diff", "--name-only", "--diff-filter=U", "-z"])
    )
    if unmerged:
        raise IdentityError(f"candidate has unmerged paths: {', '.join(unmerged)}")
    staged = _nul_paths(candidate_git(["diff", "--cached", "--name-only", "-z"]))
    if staged:
        raise IdentityError(f"candidate has staged paths: {', '.join(staged)}")

    tracked_paths = _nul_paths(candidate_git(["ls-files", "-z"]))
    untracked_paths = _nul_paths(
        candidate_git(["ls-files", "--others", "--exclude-standard", "-z"])
    )
    current_paths = tuple(
        sorted(set(tracked_paths) | set(untracked_paths), key=os.fsencode)
    )
    missing_tracked = {
        relative
        for relative in tracked_paths
        if not os.path.lexists(resolved / relative)
    }
    records: list[FileRecord] = []
    for relative in current_paths:
        record = _hash_regular_file(
            resolved,
            relative,
            allow_missing=relative in missing_tracked,
        )
        if record is not None:
            records.append(record)
    records_by_path = {record.path: record for record in records}
    untracked = tuple(
        records_by_path[path] for path in untracked_paths if path in records_by_path
    )

    head = candidate_git(["rev-parse", "HEAD"]).decode("ascii").strip()
    branch = candidate_git(["branch", "--show-current"]).decode("utf-8").strip()
    upstream_payload = candidate_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        check=False,
    )
    upstream = upstream_payload.decode("utf-8").strip() or None
    ahead: int | None = None
    behind: int | None = None
    if upstream is not None:
        counts = candidate_git(
            ["rev-list", "--left-right", "--count", f"{upstream}...HEAD"]
        )
        behind_text, ahead_text = counts.decode("ascii").strip().split()
        ahead = int(ahead_text)
        behind = int(behind_text)
    diff = candidate_git(["diff", "--binary", "--no-ext-diff", "HEAD", "--"])
    diff_sha256 = hashlib.sha256(diff).hexdigest()
    untracked_payload = [asdict(item) for item in untracked]
    combined = hashlib.sha256(
        json.dumps(
            {"head": head, "diff_sha256": diff_sha256, "untracked": untracked_payload},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    selected_runner_root = runner_root or Path(__file__).resolve().parent
    porcelain = candidate_git(
        ["status", "--porcelain=v2", "--branch", "--untracked-files=all"]
    ).decode("utf-8", errors="surrogateescape")
    final_unmerged = _nul_paths(
        candidate_git(["diff", "--name-only", "--diff-filter=U", "-z"])
    )
    if final_unmerged != unmerged:
        raise IdentityError("candidate unmerged state changed during identity capture")
    final_staged = _nul_paths(candidate_git(["diff", "--cached", "--name-only", "-z"]))
    if final_staged != staged:
        raise IdentityError("candidate staged state changed during identity capture")
    final_tracked_paths = _nul_paths(candidate_git(["ls-files", "-z"]))
    final_untracked_paths = _nul_paths(
        candidate_git(["ls-files", "--others", "--exclude-standard", "-z"])
    )
    final_missing_tracked = {
        relative
        for relative in final_tracked_paths
        if not os.path.lexists(resolved / relative)
    }
    if (
        final_tracked_paths != tracked_paths
        or final_untracked_paths != untracked_paths
        or final_missing_tracked != missing_tracked
    ):
        raise IdentityError("candidate path set changed during identity capture")
    return CandidateIdentity(
        root=resolved,
        branch=branch,
        head=head,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        porcelain_v2=porcelain,
        staged=staged,
        unmerged=unmerged,
        missing_tracked=tuple(sorted(missing_tracked, key=os.fsencode)),
        diff_sha256=diff_sha256,
        untracked=untracked,
        files=tuple(records),
        combined_sha256=combined,
        runner_sha256=_runner_hash(selected_runner_root),
        python_lines=python_lines,
        scenario_ids=scenario_ids,
    )


def _run_mirror_git(
    root: Path,
    arguments: list[str],
    *,
    environment: Mapping[str, str] | None = None,
    command_runner: GitCommandRunner | None = None,
) -> bytes:
    selected_environment = os.environ.copy()
    selected_environment.update({"LC_ALL": "C", "LANG": "C"})
    if environment is not None:
        selected_environment.update(environment)
    runner = command_runner or _default_git_command_runner
    return runner(
        ("git", *arguments),
        cwd=root,
        environment=selected_environment,
        check=True,
        failure_label="disposable Git command",
    )


def _verify_candidate_path_state(
    identity: CandidateIdentity,
    *,
    environment: Mapping[str, str] | None,
    command_runner: GitCommandRunner | None,
) -> None:
    tracked = _nul_paths(
        _git(
            identity.root,
            ["ls-files", "-z"],
            environment=environment,
            command_runner=command_runner,
        )
    )
    untracked = _nul_paths(
        _git(
            identity.root,
            ["ls-files", "--others", "--exclude-standard", "-z"],
            environment=environment,
            command_runner=command_runner,
        )
    )
    expected_untracked = tuple(record.path for record in identity.untracked)
    expected_tracked = tuple(
        sorted(
            {record.path for record in identity.files}.difference(
                expected_untracked
            ).union(identity.missing_tracked),
            key=os.fsencode,
        )
    )
    missing = tuple(
        relative
        for relative in tracked
        if not os.path.lexists(identity.root / relative)
    )
    if (
        tracked != expected_tracked
        or untracked != expected_untracked
        or missing != identity.missing_tracked
    ):
        raise IdentityError("candidate path state changed before mirror copy")


def create_candidate_mirror(
    identity: CandidateIdentity,
    destination: Path,
    *,
    environment: Mapping[str, str] | None = None,
    command_runner: GitCommandRunner | None = None,
) -> CandidateMirror:
    _verify_candidate_path_state(
        identity,
        environment=environment,
        command_runner=command_runner,
    )
    if destination.exists() and any(destination.iterdir()):
        raise IdentityError(f"candidate mirror destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for record in identity.files:
        target = destination / record.path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _read_verified_file(identity.root, record)
        target.write_bytes(data)
        target.chmod(record.mode)
    copied: list[FileRecord] = []
    for record in identity.files:
        copied_record = _hash_regular_file(destination, record.path)
        if copied_record is None:
            raise IdentityError(f"candidate mirror omitted file: {record.path}")
        copied.append(copied_record)
    copied_contents = tuple(
        (record.path, record.size, record.sha256, record.mode, record.executable)
        for record in copied
    )
    source_contents = tuple(
        (record.path, record.size, record.sha256, record.mode, record.executable)
        for record in identity.files
    )
    if copied_contents != source_contents:
        raise IdentityError("candidate mirror manifest does not match live candidate")
    _verify_candidate_path_state(
        identity,
        environment=environment,
        command_runner=command_runner,
    )

    mirror_commands = (
        ["init", "-b", "qualification-candidate"],
        ["config", "core.hooksPath", "/dev/null"],
        ["config", "user.name", "Pyganini Qualification"],
        ["config", "user.email", "qualification@invalid"],
        ["config", "commit.gpgsign", "false"],
        ["add", "--all"],
    )
    for command in mirror_commands:
        _run_mirror_git(
            destination,
            command,
            environment=environment,
            command_runner=command_runner,
        )
    fixed_environment = {
        "GIT_AUTHOR_NAME": "Pyganini Qualification",
        "GIT_AUTHOR_EMAIL": "qualification@invalid",
        "GIT_COMMITTER_NAME": "Pyganini Qualification",
        "GIT_COMMITTER_EMAIL": "qualification@invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }
    commit_environment = dict(environment or {})
    commit_environment.update(fixed_environment)
    _run_mirror_git(
        destination,
        ["commit", "--no-gpg-sign", "-m", "qualification candidate mirror"],
        environment=commit_environment,
        command_runner=command_runner,
    )
    commit = (
        _run_mirror_git(
            destination,
            ["rev-parse", "HEAD"],
            environment=environment,
            command_runner=command_runner,
        )
        .decode("ascii")
        .strip()
    )
    mirrored_identity = replace(identity, disposable_commit=commit)
    return CandidateMirror(root=destination, commit=commit, identity=mirrored_identity)
