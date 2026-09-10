from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from harness.contracts import Candidate, CheckResult, TaskSpec, VerificationReport
from harness.experiments import simple, final_registry
from harness.adapters.repository import RepositoryAgent, system_prompt
from harness.verification import registry as development


TASK = TaskSpec("test", "sql_search", "Implement search_users in solution.py", "test-v1")
BUDGET = simple.protocol()["budget"]


class Verifier:
    image = "test-image"

    def __init__(self, image="test-image", *, suite="development", fail_first=False, events=None):
        self.suite, self.calls, self.fail_first, self.events = suite, 0, fail_first, events

    def verify(self, task, candidate, output):
        output.mkdir(parents=True)
        self.calls += 1
        if self.events is not None:
            self.events.append(self.suite)
        registry = final_registry if self.suite == "final" else development
        checks = tuple(CheckResult(s.id, s.version, candidate.sha256,
                                   "failed" if self.fail_first and self.calls == 1 else "passed",
                                   s.kind, "test failure", "execution.log") for s in registry.for_family(task.family))
        return VerificationReport(task, candidate.sha256, registry.fingerprint(), {"suite": self.suite}, checks, (), ())


class Agent:
    def __init__(self, status="ok", cleanup=True, events=None):
        self.status, self.cleanup, self.events = status, cleanup, events
        self.prompts, self.limits = [], []

    def run(self, workspace, output, prompt, **limits):
        output.mkdir()
        self.prompts.append(prompt)
        self.limits.append(limits)
        if self.events is not None:
            self.events.append("agent")
        (workspace / "solution.py").write_text(f"# candidate {len(self.prompts)}\ndef search_users(c,q): return []\n")
        return {"status": self.status, "cleanup_confirmed": self.cleanup, "elapsed_seconds": 12,
                "sdk": {"execution_status": "finished" if self.status == "ok" else "running"}}


def test_final_verifier_cannot_enter_repair(tmp_path):
    with pytest.raises(ValueError, match="Final verifier"):
        simple.generate(TASK, "full", tmp_path / "run", Agent(), Verifier(suite="final"), "common", BUDGET, {})


def test_repair_budget_feedback_and_fresh_final(tmp_path):
    agent = Agent()
    result = simple.generate(TASK, "full", tmp_path / "run", agent, Verifier(fail_first=True), "common", BUDGET, {"selected": []})
    assert result["external_repairs"] == 1 and result["status"] == "completed"
    assert agent.limits == [{"timeout": 200, "iterations": 20}, {"timeout": 100, "iterations": 10}]
    assert "candidate_sha256" in agent.prompts[1] and "final.sql_search" not in agent.prompts[1]
    assert not (tmp_path / "run/final-evaluation").exists()
    scored = simple.finalize(TASK, result, tmp_path / "run", Verifier(suite="final"))
    assert scored["joint_pass"]
    (tmp_path / "run" / result["final_candidate"]).write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        simple.finalize(TASK, result, tmp_path / "run", Verifier(suite="final"))


@pytest.mark.parametrize("arm", ["baseline", "policy"])
def test_controls_never_get_external_feedback(tmp_path, arm):
    agent = Agent()
    result = simple.generate(TASK, arm, tmp_path / arm, agent, Verifier(fail_first=True), "common", BUDGET, {"selected": []})
    assert len(agent.prompts) == 1 and result["external_repairs"] == 0
    assert agent.limits[0] == {"timeout": 300, "iterations": 30}
    assert not (tmp_path / arm / "feedback.json").exists()


@pytest.mark.parametrize("status,cleanup", [("incomplete", True), ("timeout", True), ("ok", False)])
def test_unfinished_or_unclean_agent_cannot_repair_or_pass(tmp_path, status, cleanup):
    agent = Agent(status, cleanup)
    result = simple.generate(TASK, "verification", tmp_path / "run", agent, Verifier(fail_first=True), "common", BUDGET)
    assert len(agent.prompts) == 1
    scored = simple.finalize(TASK, result, tmp_path / "run", Verifier(suite="final"))
    assert not scored["joint_pass"]


def test_missing_guidance_is_not_silent_baseline(tmp_path):
    agent = Agent()
    result = simple.generate(TASK, "policy", tmp_path / "run", agent, Verifier(), "common", BUDGET)
    assert result["status"] == "advisor_error" and not agent.prompts


def test_stale_or_partial_evidence_is_unhealthy(tmp_path):
    candidate = Candidate(TASK.task_id, b"pass\n")
    report = Verifier().verify(TASK, candidate, tmp_path / "dev")
    for invalid in (replace(report, candidate_sha256="stale"), replace(report, checks=report.checks[:-1]),
                    replace(report, registry_sha256="stale"), replace(report, environment={"suite": "development", "cleanup_error": "yes"})):
        assert not simple.summarize(invalid, TASK, candidate, "development")["healthy"]


def test_matrix_finishes_generation_before_final_scoring(tmp_path, monkeypatch):
    plan = simple.protocol()
    events = []
    agent = Agent(events=events)
    manifest = {"protocol": plan, "source_sha256": simple.sources(), "coding_python": "unused", "agent_image": "unused", "verifier_image": "unused"}
    monkeypatch.setattr(simple, "load_manifest", lambda _: manifest)
    monkeypatch.setattr(simple, "RepositoryAgent", lambda *a, **kw: agent)
    monkeypatch.setattr(simple, "DockerVerifier", lambda image, suite="development": Verifier(suite=suite, events=events))
    selected = []

    class Advisor:
        def select(self, task, timeout):
            selected.append(task.task_id)
            return {"selected": []}

    monkeypatch.setattr(simple, "MCPAdvisor", Advisor)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    rows = simple.run(tmp_path)
    assert len(selected) == 9 and len(rows) == 36
    assert len(agent.prompts) == 36
    first_final = events.index("final")
    assert "agent" not in events[first_final:]
    assert events[:first_final].count("agent") == 36
    assert len(json.loads((tmp_path / "candidates-frozen.json").read_text())) == 36
    assert all(row["joint_pass"] for row in rows)


def test_final_manifest_disjoint_ids_and_expected_counts():
    assert not {c.id for c in development.CHECKS} & {c.id for c in final_registry.CHECKS}
    assert len(final_registry.CHECKS) == 26


def test_agent_language_label_is_not_a_benchmark_allowlist():
    agent = RepositoryAgent("unused", language="Rust")
    assert agent.language == "Rust"
    assert "Rust repository task" in system_prompt(agent.language)
    assert "TypeScript repository task" in system_prompt("TypeScript")
    with pytest.raises(ValueError, match="nonempty"):
        system_prompt("")


def test_freeze_reload_preserves_virtual_environment_interpreter(tmp_path, monkeypatch):
    base = tmp_path / "base-python"
    base.write_text("placeholder")
    python = tmp_path / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(base)
    qualification = tmp_path / "qualification"
    qualification.mkdir()
    (qualification / "qualification.json").write_text("{}")
    smoke = tmp_path / "smoke"
    smoke.mkdir()
    source = {"README.md": simple.digest(simple.ROOT / "README.md")}
    (smoke / "smoke.json").write_text(json.dumps({"passed": True, "source_sha256": source}))
    monkeypatch.setattr(simple, "sources", lambda: source)
    monkeypatch.setattr(simple, "validate_qualification", lambda _: {"image_id": "sha256:test"})
    monkeypatch.setattr(simple, "image_id", lambda value: value)
    monkeypatch.setattr(simple, "packages", lambda path: {"environment": str(path)})
    monkeypatch.setattr(simple, "model_settings", lambda *a: {})
    output = tmp_path / "execution"
    manifest = simple.freeze(output, qualification, smoke, python)
    assert manifest["coding_python"] == str(python.absolute())
    assert manifest["coding_python"] != str(python.resolve())
    assert simple.load_manifest(output)["coding_python"] == str(python.absolute())


@pytest.mark.skipif(not simple.PYTHON.exists(), reason="OpenHands SDK environment unavailable")
def test_sdk_subclass_retains_native_templates_and_python_context():
    # Real SDK construction catches prompt resolution/ignored-keyword problems
    # without a model request, Docker, or access to credentials.
    code = '''from harness.adapters.repository_sdk import MeasuredAgent
from harness.adapters.repository import system_prompt
from openhands.sdk import AgentContext
from openhands.sdk.llm import LLM
a = MeasuredAgent(llm=LLM(model="openai/gpt-5.4-mini", api_key="unused"),
                  agent_context=AgentContext(system_message_suffix=system_prompt("Python")))
assert "You are OpenHands" in a.static_system_message
assert "Python repository task" in a.dynamic_context
assert a._step_calls == 0
'''
    completed = subprocess.run([str(simple.PYTHON), "-c", code], cwd=simple.ROOT,
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr[-3000:]
