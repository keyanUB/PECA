import json
import os
from pathlib import Path

import pytest

from harness.contracts import Candidate, ObligationBinding, TaskSpec
from harness.verification.runner import DockerVerifier


pytestmark = pytest.mark.skipif(os.getenv("PECA_TEST_DOCKER") != "1", reason="Set PECA_TEST_DOCKER=1 for Docker integration")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("family", ["sql_search", "document_read", "tar_extract"])
@pytest.mark.parametrize("kind", ["secure", "vulnerable"])
def test_references_and_vulnerabilities(family, kind, tmp_path):
    task = TaskSpec("reference", family, "Verify known fixture", "fixture-v1")
    candidate = Candidate.from_file(task.task_id, FIXTURES / f"{family}_{kind}.py")
    report = DockerVerifier().verify(task, candidate, tmp_path / "evidence")
    assert not any(c.status in ("error", "timeout") for c in report.checks)
    if kind == "secure":
        assert all(c.status == "passed" for c in report.checks)
    else:
        assert any(c.kind == "security" and c.status == "failed" for c in report.checks)
    assert all(c.candidate_sha256 == candidate.sha256 for c in report.checks)
    assert report.environment["image_id"].startswith("sha256:")
    saved = json.loads((tmp_path / "evidence/report.json").read_text())
    assert saved["candidate_sha256"] == candidate.sha256


def test_leaf_symlink_gap_detected_and_baseline_cannot_be_disabled(tmp_path):
    candidate = Candidate.from_file("tar", FIXTURES / "tar_parent_only.py")
    bindings = (ObligationBinding("containment", ("tar_extract.preexisting_symlink", "tar_extract.preexisting_leaf_symlink")),
                ObligationBinding("race_safety"))
    report = DockerVerifier().verify(TaskSpec("tar", "tar_extract", "Extract archive", "fixture-v1"),
                                     candidate, tmp_path / "evidence", bindings)
    statuses = {c.check_id: c.status for c in report.checks}
    assert len(statuses) == 8
    assert statuses["tar_extract.preexisting_symlink"] == "passed"
    assert statuses["tar_extract.preexisting_leaf_symlink"] == "failed"
    assert [o.status for o in report.obligations] == ["failed", "unverified"]


def test_timeout_is_not_a_pass(tmp_path):
    report = DockerVerifier().verify(TaskSpec("hang", "sql_search", "query", "fixture", 2),
                                     Candidate("hang", b"while True: pass"), tmp_path / "evidence")
    assert {c.status for c in report.checks} == {"timeout"}
    assert "cleanup_error" not in report.environment


def test_isolation_and_secret_environment_not_forwarded(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "PECA_TEST_SECRET_MUST_NOT_REACH_CANDIDATE")
    assertions = b'''import os, socket
assert os.getuid() == 65534
assert 'OPENAI_API_KEY' not in os.environ
assert [name for _, name in socket.if_nameindex()] == ['lo']
for path in ('/probes.py', '/candidate.py', '/should_not_be_writable'):
    try:
        open(path, 'w')
    except OSError:
        pass
    else:
        raise AssertionError('read-only isolation failed')
'''
    candidate = Candidate("isolated", assertions + (FIXTURES / "sql_search_secure.py").read_bytes())
    report = DockerVerifier().verify(TaskSpec("isolated", "sql_search", "query", "fixture"), candidate, tmp_path / "evidence")
    assert all(c.status == "passed" for c in report.checks)


@pytest.mark.parametrize("source", [b"invalid python !", b"import os; os._exit(0)"])
def test_import_errors_and_missing_results_are_errors(source, tmp_path):
    report = DockerVerifier().verify(TaskSpec("bad", "sql_search", "query", "fixture"),
                                     Candidate("bad", source), tmp_path / "evidence")
    assert {c.status for c in report.checks} == {"error"}
