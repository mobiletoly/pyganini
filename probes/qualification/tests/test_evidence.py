from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from qualification_probes.evidence import (
    EvidenceError,
    EvidenceWriter,
    normalize_metadata,
)


def test_metadata_normalization_does_not_rewrite_raw_streams(tmp_path: Path) -> None:
    temporary_root = tmp_path / "work"
    repository_root = tmp_path / "candidate"
    temporary_root.mkdir()
    repository_root.mkdir()
    raw = f"failure in {temporary_root}/app and {repository_root}/route.py\n".encode()
    writer = EvidenceWriter(
        tmp_path / "evidence",
        temporary_root=temporary_root,
        pyganini_root=repository_root,
    )

    stdout_record, stderr_record = writer.write_streams("Q001", raw, b"")

    assert (writer.staging / stdout_record.path).read_bytes() == raw
    assert stdout_record.sha256 == hashlib.sha256(raw).hexdigest()
    normalized = normalize_metadata(
        [str(temporary_root / "app"), str(repository_root / "route.py")],
        temporary_root=temporary_root,
        pyganini_root=repository_root,
    )
    assert normalized == ["<qualification-temp>/app", "<pyganini-root>/route.py"]
    assert stderr_record.byte_length == 0


def test_finalize_writes_report_and_bytewise_checksum_inventory(tmp_path: Path) -> None:
    writer = EvidenceWriter(
        tmp_path / "evidence",
        temporary_root=tmp_path / "work",
        pyganini_root=tmp_path / "candidate",
    )
    stdout_record, stderr_record = writer.write_streams("Q001", b"out\n", b"err\n")
    writer.add_scenario(
        {
            "id": "Q001",
            "name": "identity",
            "stdout": stdout_record.as_dict(),
            "stderr": stderr_record.as_dict(),
            "status": "pass",
        }
    )

    output = writer.finalize(
        candidate={"root": str(tmp_path / "candidate"), "combined_sha256": "a" * 64},
        environment={"python_lines": ["3.14"]},
        verdict="PASS_TO_PERFORMANCE_QUALIFICATION",
    )

    assert output == tmp_path / "evidence"
    report = (output / "report.json").read_text(encoding="ascii")
    assert '"schema": "pyganini.qualification.v1"' in report
    assert str(tmp_path) not in report
    checksum_lines = (output / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    assert [line.split("  ", 1)[1] for line in checksum_lines] == [
        "raw/Q001.stderr",
        "raw/Q001.stdout",
        "report.json",
    ]


def test_finalize_rejects_secret_metadata_and_preserves_staging(tmp_path: Path) -> None:
    writer = EvidenceWriter(
        tmp_path / "evidence",
        temporary_root=tmp_path / "work",
        pyganini_root=tmp_path / "candidate",
    )

    with pytest.raises(EvidenceError, match="secret-bearing"):
        writer.finalize(
            candidate={"combined_sha256": "a" * 64},
            environment={"csrf_token": "do-not-record"},
            verdict="BLOCKED_EVIDENCE_INCOMPLETE",
        )

    assert writer.staging.exists()
    assert not (tmp_path / "evidence").exists()


def test_finalize_translates_report_write_failure_and_retains_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = EvidenceWriter(
        tmp_path / "evidence",
        temporary_root=tmp_path / "work",
        pyganini_root=tmp_path / "candidate",
    )
    original_write_bytes = Path.write_bytes

    def fail_report_write(path: Path, data: bytes) -> int:
        if path.name == "report.json":
            raise OSError("disk denied")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_report_write)

    with pytest.raises(EvidenceError, match=r"staging retained.*disk denied"):
        writer.finalize(
            candidate={"combined_sha256": "a" * 64},
            environment={"python_lines": ["3.14"]},
            verdict="BLOCKED_EVIDENCE_INCOMPLETE",
        )

    assert writer.staging.exists()
    assert not writer.output.exists()


def test_stream_write_failure_makes_staging_non_finalizable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = EvidenceWriter(
        tmp_path / "evidence",
        temporary_root=tmp_path / "work",
        pyganini_root=tmp_path / "candidate",
    )
    original_write_bytes = Path.write_bytes

    def fail_stderr_write(path: Path, data: bytes) -> int:
        if path.name == "Q001.stderr":
            raise OSError("stream denied")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_stderr_write)
    with pytest.raises(EvidenceError, match=r"stream write failed.*stream denied"):
        writer.write_streams("Q001", b"partial stdout", b"missing stderr")
    monkeypatch.setattr(Path, "write_bytes", original_write_bytes)

    with pytest.raises(EvidenceError, match=r"finalization refused.*stream denied"):
        writer.finalize(
            candidate={"combined_sha256": "a" * 64},
            environment={"python_lines": ["3.14"]},
            verdict="BLOCKED_EVIDENCE_INCOMPLETE",
        )

    assert writer.staging.exists()
    assert not writer.output.exists()


def test_finalize_rejects_a_recreated_qualification_root(tmp_path: Path) -> None:
    temporary_root = tmp_path / "qualification-root"
    temporary_root.mkdir()
    writer = EvidenceWriter(
        tmp_path / "evidence",
        temporary_root=temporary_root,
        pyganini_root=tmp_path / "candidate",
    )

    with pytest.raises(EvidenceError, match="temporary root remains"):
        writer.finalize(
            candidate={"combined_sha256": "a" * 64},
            environment={"python_lines": ["3.14"]},
            verdict="BLOCKED_EVIDENCE_INCOMPLETE",
        )

    assert writer.staging.exists()
    assert not writer.output.exists()
