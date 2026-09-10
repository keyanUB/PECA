from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from harness.contracts import Candidate, CheckResult, ObligationBinding, TaskSpec
from harness.verification.registry import CHECKS, fingerprint, validate_bindings
from harness.verification.runner import DockerVerifier, obligation_results


def test_candidate_is_immutable_snapshot(tmp_path):
    path = tmp_path / "solution.py"
    path.write_text("original")
    candidate = Candidate.from_file("task", path)
    path.write_text("changed")
    assert candidate.source == b"original"
    assert candidate.sha256 == Candidate("task", b"original").sha256
    with pytest.raises(FrozenInstanceError):
        candidate.source = b"other"


def test_candidate_rejects_symlinks_and_oversize(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"a" * 200_001)
    link = tmp_path / "link.py"
    link.symlink_to(source)
    for path in (source, link):
        with pytest.raises(ValueError):
            Candidate.from_file("task", path)


def test_registry_rejects_commands_and_cross_family_bindings():
    for check in ("rm -rf /", "document_read.symlink"):
        with pytest.raises(ValueError):
            validate_bindings("sql_search", (ObligationBinding("policy", (check,)),))
    assert len({c.id for c in CHECKS}) == len(CHECKS) == 22
    assert len(fingerprint()) == 64


def test_unmapped_obligations_are_not_passes():
    bindings = (ObligationBinding("missing"), ObligationBinding("mapped", ("sql_search.boolean_sql_injection",)))
    checks = (CheckResult("sql_search.boolean_sql_injection", "1", "hash", "failed", "security", "", "log"),)
    results = obligation_results(bindings, checks)
    assert [r.status for r in results] == ["unverified", "failed"]


def test_backend_failure_is_error_not_security_failure(tmp_path):
    task = TaskSpec("task", "sql_search", "search users", "fixture")
    report = DockerVerifier(docker="/nonexistent/docker").verify(task, Candidate("task", b"pass"), tmp_path / "result")
    assert len(report.checks) == 8
    assert {c.status for c in report.checks} == {"error"}
    assert (tmp_path / "result/report.json").is_file()
    with pytest.raises(FileExistsError):
        DockerVerifier().verify(task, Candidate("task", b"pass"), tmp_path / "result")


def test_reject_mismatched_task_before_execution(tmp_path):
    with pytest.raises(ValueError, match="task ID"):
        DockerVerifier().verify(TaskSpec("a", "sql_search", "query", "revision"),
                                Candidate("b", b"pass"), tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()
