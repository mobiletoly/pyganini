from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast


class EvidenceError(RuntimeError):
    """Report evidence staging or finalization failure."""


@dataclass(frozen=True, slots=True)
class StreamRecord:
    path: str
    byte_length: int
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_metadata(
    value: object, *, temporary_root: Path, pyganini_root: Path
) -> object:
    replacements = (
        (str(temporary_root), "<qualification-temp>"),
        (str(pyganini_root), "<pyganini-root>"),
        (str(Path.home()), "<home>"),
    )
    if isinstance(value, str):
        normalized = value
        for source, replacement in replacements:
            normalized = normalized.replace(source, replacement)
        return normalized
    if isinstance(value, list):
        list_values = cast(list[object], value)
        return [
            normalize_metadata(
                item, temporary_root=temporary_root, pyganini_root=pyganini_root
            )
            for item in list_values
        ]
    if isinstance(value, tuple):
        tuple_values = cast(tuple[object, ...], value)
        return [
            normalize_metadata(
                item, temporary_root=temporary_root, pyganini_root=pyganini_root
            )
            for item in tuple_values
        ]
    if isinstance(value, dict):
        mapping_values = cast(dict[object, object], value)
        return {
            str(key): normalize_metadata(
                item, temporary_root=temporary_root, pyganini_root=pyganini_root
            )
            for key, item in mapping_values.items()
        }
    return value


_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:authorization|cookie|csrf_token|password|secret|session|token)(?:$|_)",
    re.IGNORECASE,
)


def _reject_sensitive_keys(value: object, *, path: str = "report") -> None:
    if isinstance(value, dict):
        mapping_values = cast(dict[object, object], value)
        for key, item in mapping_values.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                raise EvidenceError(
                    f"secret-bearing metadata key is forbidden: {path}.{key_text}"
                )
            _reject_sensitive_keys(item, path=f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        collection_values = cast(list[object] | tuple[object, ...], value)
        for index, item in enumerate(collection_values):
            _reject_sensitive_keys(item, path=f"{path}[{index}]")


class EvidenceWriter:
    def __init__(
        self, output: Path, *, temporary_root: Path, pyganini_root: Path
    ) -> None:
        self.output = output
        self.temporary_root = temporary_root
        self.pyganini_root = pyganini_root
        self.staging = output.parent / f".{output.name}.staging-{uuid.uuid4().hex}"
        try:
            if output.exists() and (not output.is_dir() or any(output.iterdir())):
                raise EvidenceError(
                    f"evidence output must be absent or empty: {output}"
                )
            self.staging.mkdir(parents=True)
            (self.staging / "raw").mkdir()
        except OSError as error:
            raise EvidenceError(
                f"evidence staging failed at {self.staging}: {error}"
            ) from error
        self._scenarios: list[dict[str, Any]] = []
        self._incomplete_error: str | None = None

    def write_streams(
        self, scenario_id: str, stdout: bytes, stderr: bytes
    ) -> tuple[StreamRecord, StreamRecord]:
        if re.fullmatch(r"Q[0-9]{3}", scenario_id) is None:
            raise EvidenceError(f"invalid scenario ID for raw streams: {scenario_id}")
        stdout_path = Path("raw") / f"{scenario_id}.stdout"
        stderr_path = Path("raw") / f"{scenario_id}.stderr"
        try:
            (self.staging / stdout_path).write_bytes(stdout)
            (self.staging / stderr_path).write_bytes(stderr)
        except OSError as error:
            self._incomplete_error = (
                "evidence stream write failed; staging retained at "
                f"{self.staging}: {error}"
            )
            raise EvidenceError(self._incomplete_error) from error
        return (
            StreamRecord(stdout_path.as_posix(), len(stdout), _sha256(stdout)),
            StreamRecord(stderr_path.as_posix(), len(stderr), _sha256(stderr)),
        )

    def add_scenario(self, record: dict[str, Any]) -> None:
        self._scenarios.append(record)

    def finalize(
        self, *, candidate: dict[str, Any], environment: dict[str, Any], verdict: str
    ) -> Path:
        if self._incomplete_error is not None:
            raise EvidenceError(
                "evidence finalization refused; staging retained at "
                f"{self.staging}: {self._incomplete_error}"
            )
        if self.temporary_root.exists():
            raise EvidenceError(
                "evidence finalization refused because the qualification "
                f"temporary root remains; staging retained at {self.staging}"
            )
        report = {
            "schema": "pyganini.qualification.v1",
            "candidate": candidate,
            "environment": environment,
            "scenarios": self._scenarios,
            "verdict": verdict,
        }
        _reject_sensitive_keys(report)
        normalized = normalize_metadata(
            report, temporary_root=self.temporary_root, pyganini_root=self.pyganini_root
        )
        report_bytes = (
            json.dumps(normalized, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        ).encode("ascii")
        try:
            (self.staging / "report.json").write_bytes(report_bytes)
            evidence_paths = [
                path.relative_to(self.staging)
                for path in self.staging.rglob("*")
                if path.is_file() and path.name != "SHA256SUMS"
            ]
            evidence_paths.sort(key=lambda path: os.fsencode(path.as_posix()))
            checksum_lines = [
                f"{_sha256((self.staging / relative).read_bytes())}  "
                f"{relative.as_posix()}"
                for relative in evidence_paths
            ]
            (self.staging / "SHA256SUMS").write_text(
                "\n".join(checksum_lines) + "\n", encoding="ascii"
            )
            if self.output.exists():
                self.output.rmdir()
            self.staging.rename(self.output)
        except OSError as error:
            raise EvidenceError(
                "evidence finalization failed; staging retained at "
                f"{self.staging}: {error}"
            ) from error
        return self.output
