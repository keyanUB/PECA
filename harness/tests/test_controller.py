from dataclasses import replace
import json

import pytest

from harness.adapters.openhands import AgentResult, OpenHandsAdapter
from harness.contracts import Candidate, CheckResult, ObligationBinding, ObligationResult, TaskSpec, VerificationReport
from harness.controller import Controller, RunBudget
from harness.verification.registry import fingerprint, for_family


TASK = TaskSpec("task", "sql_search", "Implement search_users", "fixture-v1")


class ScriptedAgent:
    def __init__(self, *sources):
        self.sources = iter(sources)
        self.calls = []

    def run(self, task, workspace, output, prompt, timeout, session_id):
        self.calls.append({"prompt": prompt, "session_id": session_id})
        source = next(self.sources)
        return AgentResult("ok", Candidate(task.task_id, source), "test-session")


class ScriptedVerifier:
    def __init__(self, *failures, status="failed"):
        self.failures = iter(failures)
        self.status = status

    def verify(self, task, candidate, output, bindings):
        failed = next(self.failures)
        output.mkdir()
        checks = tuple(CheckResult(c.id, c.version, candidate.sha256,
                       self.status if c.name in failed else "passed", c.kind,
                       "observed failure" if c.name in failed else "", "execution.log") for c in for_family(task.family))
        report = VerificationReport(task, candidate.sha256, fingerprint(), {}, checks,
                                    tuple(ObligationResult(b.obligation_id, b.check_ids, "unverified") for b in bindings), ())
        (output / "report.json").write_text(json.dumps(report.to_dict()))
        return report


def test_secure_seed_needs_no_agent_or_repair(tmp_path):
    agent = ScriptedAgent()
    result = Controller(agent, ScriptedVerifier(set())).run(TASK, tmp_path / "run", initial_candidate=Candidate("task", b"secure"))
    assert result["decision"]["decision"] == "accept"
    assert result["agent_calls"] == result["repairs"] == 0
    assert not agent.calls


def test_repairs_regressions_and_resumes_same_session(tmp_path):
    agent = ScriptedAgent(b"vulnerable", b"functional-regression", b"fixed")
    verifier = ScriptedVerifier({"boolean_sql_injection"}, {"case_insensitive_lookup"}, set())
    result = Controller(agent, verifier).run(TASK, tmp_path / "run")
    assert result["decision"]["decision"] == "accept"
    assert result["repairs"] == 2 and result["agent_calls"] == 3
    assert [c["session_id"] for c in agent.calls] == [None, "test-session", "test-session"]
    feedback = json.loads((tmp_path / "run/feedback-2.json").read_text())
    assert feedback["failures"][0]["regression"] is True
    assert feedback["failures"][0]["kind"] == "functional"


def test_repeated_candidate_stops_without_spending_remaining_rounds(tmp_path):
    result = Controller(ScriptedAgent(b"same"), ScriptedVerifier({"boolean_sql_injection"}, {"boolean_sql_injection"})).run(
        TASK, tmp_path / "run", initial_candidate=Candidate("task", b"same"))
    assert result["decision"]["decision"] == "incomplete"
    assert "no progress" in result["decision"]["reason"]
    assert result["repairs"] == 1


def test_repair_budget_exhaustion_preserves_last_candidate(tmp_path):
    agent = ScriptedAgent(b"still vulnerable")
    result = Controller(agent, ScriptedVerifier({"boolean_sql_injection"}, {"boolean_sql_injection"}),
                        budget=RunBudget(max_repairs=1)).run(TASK, tmp_path / "run", initial_candidate=Candidate("task", b"original"))
    assert result["decision"]["decision"] == "budget_exhausted"
    assert result["decision"]["candidate_sha256"] == Candidate("task", b"still vulnerable").sha256


@pytest.mark.parametrize("status", ["error", "timeout", "unverified"])
def test_infrastructure_or_missing_verification_does_not_trigger_repair(tmp_path, status):
    agent = ScriptedAgent()
    result = Controller(agent, ScriptedVerifier({"boolean_sql_injection"}, status=status)).run(
        TASK, tmp_path / "run", initial_candidate=Candidate("task", b"code"))
    assert result["decision"]["decision"] == "incomplete"
    assert not agent.calls


def test_unmapped_obligation_blocks_acceptance(tmp_path):
    result = Controller(ScriptedAgent(), ScriptedVerifier(set())).run(TASK, tmp_path / "run",
        (ObligationBinding("unknown"),), Candidate("task", b"code"))
    assert result["decision"]["decision"] == "incomplete"


@pytest.mark.parametrize("corruption", ["hash", "missing", "cleanup", "registry", "version"])
def test_bad_evidence_cannot_be_accepted(tmp_path, corruption):
    class BadVerifier(ScriptedVerifier):
        def verify(self, *args):
            report = super().verify(*args)
            if corruption == "hash": return replace(report, candidate_sha256="wrong")
            if corruption == "missing": return replace(report, checks=report.checks[:-1])
            if corruption == "registry": return replace(report, registry_sha256="old")
            if corruption == "version": return replace(report, checks=(replace(report.checks[0], check_version="old"), *report.checks[1:]))
            return replace(report, environment={"cleanup_error": "failed"})
    result = Controller(ScriptedAgent(), BadVerifier(set())).run(TASK, tmp_path / "run", initial_candidate=Candidate("task", b"code"))
    assert result["decision"]["decision"] == "incomplete"


def test_advisor_failure_is_recorded_and_agent_does_not_run(tmp_path):
    class BadAdvisor:
        def select(self, task, timeout): raise RuntimeError("API failure")
    agent = ScriptedAgent()
    result = Controller(agent, ScriptedVerifier(), BadAdvisor()).run(TASK, tmp_path / "run")
    assert result["decision"]["decision"] == "incomplete"
    assert not agent.calls and (tmp_path / "run/result.json").is_file()


def test_agent_timeout_is_bounded_and_keeps_candidate(tmp_path):
    class TimedAgent:
        def run(self, *args): return AgentResult("timeout", Candidate("task", b"partial"), None, "timeout")
    result = Controller(TimedAgent(), ScriptedVerifier()).run(TASK, tmp_path / "run")
    assert result["decision"]["decision"] == "budget_exhausted"
    assert result["decision"]["candidate_sha256"] == Candidate("task", b"partial").sha256


def test_total_budget_expiration_stops_before_generation(tmp_path, monkeypatch):
    ticks = iter([0, 2, 2])
    monkeypatch.setattr("harness.controller.time.monotonic", lambda: next(ticks))
    result = Controller(ScriptedAgent(), ScriptedVerifier(), budget=RunBudget(total_seconds=1)).run(TASK, tmp_path / "run")
    assert result["decision"]["decision"] == "budget_exhausted"
    assert result["agent_calls"] == 0


def test_local_execution_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="not sandboxed"):
        OpenHandsAdapter()
