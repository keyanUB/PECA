"""Exercise repair termination and policy delivery without model calls."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.benchmarks.pilot import POLICY_FILE, default_budget, run_one
from harness.repository import RepositorySnapshot
from harness.sandbox import Sandbox


def run_case(tmp_path, *, statuses=None, development=None, condition="full", budget=None,
             seconds=1, write_target=True, read_policy_rounds=None, cleanup=True):
    calls, phases = [], []
    guidance = {"selected": [{"policy_id": "SCP-test", "policy": {"text": "Validate input"},
                              "guidance": "POLICY CONTENT SENTINEL"}]}

    class Agent:
        def run(self, workspace, output, prompt, **limits):
            index = len(calls)
            calls.append({"prompt": prompt, **limits})
            if write_target:
                (workspace / "target.c").write_text(f"int implementation = {index};\n")
            if condition in ("policy", "full"):
                control = limits["control"]
                assert control.parent != workspace
                assert json.loads((control / "policy.json").read_text())["selected"][0]["guidance"] == "POLICY CONTENT SENTINEL"
                assert json.loads((control.parent / "guidance-audit.json").read_text()) == guidance
                assert not (workspace / "policy.json").exists()
                sdk = output / 'sdk'
                sdk.mkdir(parents=True)
                text = (control / 'policy.json').read_text()
                if read_policy_rounds is not None and not read_policy_rounds[index]:
                    text = text[:10]
                (sdk / 'commands.jsonl').write_text(json.dumps({'command': f'cat {POLICY_FILE}',
                                                               'exit_code': 0, 'output': text}) + '\n')
            else:
                assert "control" not in limits
            return {"status": statuses[index] if statuses else "ok", "elapsed_seconds": seconds,
                    "cleanup_confirmed": cleanup}

    class Benchmark:
        def verify(self, task, snapshot, output):
            assert set(task) == {'request', 'target'}
            output.mkdir()
            phases.append('development')
            index = len(phases) - 1
            (output / "development.log").write_text(f"PUBLIC FAILURE {index}")
            return {"status": development[index] if development else "failed"}

    result = run_one(Benchmark(), {"id": "t", "target": "target.c", "request": "Implement the task"},
                     RepositorySnapshot((("target.c", b"// <MASK>\n", 0o644),)), condition,
                     tmp_path / "run", Agent(), guidance, budget or default_budget())
    return result, calls, phases


def test_default_stops_after_one_repair_and_only_uses_developer_feedback(tmp_path):
    result, calls, phases = run_case(tmp_path)
    assert result["external_repairs"] == 1
    assert [c["iterations"] for c in calls] == [60, 60]
    assert [c["timeout"] for c in calls] == [300, 300]
    assert result["allocated_iterations"] == 120
    assert phases == ["development"] * 2
    assert result["scoring_status"] == "not_scored"
    for index, call in enumerate(calls):
        assert POLICY_FILE in call["prompt"]
        assert "POLICY CONTENT SENTINEL" not in call["prompt"]
        assert "HIDDEN POC SENTINEL" not in call["prompt"]
        if index:
            assert f"PUBLIC FAILURE {index - 1}" in call["prompt"]
    assert result["policy_file"]["bytes"] > 0
    assert all(change["path"] == "target.c" for r in result["rounds"] for change in r["changed_files"])


@pytest.mark.parametrize('cleanup', [False, None])
def test_uncertain_cleanup_blocks_candidate_capture_and_evaluation(tmp_path, cleanup):
    result, calls, phases = run_case(tmp_path, cleanup=cleanup)
    assert result['status'] == 'error'
    assert result['scoring_status'] == 'not_scored'
    assert len(calls) == len(result['agent_calls']) == 1
    assert phases == []
    assert not list((tmp_path / 'run').glob('candidate-*'))


def test_incomplete_target_can_be_repaired_but_success_requires_finished_agent(tmp_path):
    result, calls, _ = run_case(tmp_path, statuses=["incomplete", "ok"], development=["failed", "passed"])
    assert len(calls) == 2
    assert result["external_repairs"] == 1
    assert result["status"] == "ok"
    assert "joint_pass" not in result
    other, calls, _ = run_case(tmp_path / "other", statuses=["incomplete"], development=["passed"])
    assert len(calls) == 1
    assert other["status"] == "incomplete"


def test_read_coverage_is_checked_on_every_round_separately_from_code_success(tmp_path):
    result, _, _ = run_case(tmp_path, development=['failed', 'passed'], read_policy_rounds=[True, False])
    assert [r['policy_delivery']['complete'] for r in result['rounds']] == [True, False]
    assert result['policy_delivery_complete'] is False
    assert result['status'] == 'ok'  # Treatment exposure is distinct from completion.
    result, _, _ = run_case(tmp_path / 'complete', development=['failed', 'passed'])
    assert result['policy_delivery_complete'] is True


@pytest.mark.parametrize("status", ["error", "timeout", "incomplete"])
def test_missing_target_does_not_trigger_repair_or_hide_operational_error(tmp_path, status):
    result, calls, _ = run_case(tmp_path, statuses=[status], write_target=False)
    assert len(calls) == 1
    assert result["status"] == status
    assert result["external_repairs"] == 0


@pytest.mark.parametrize("condition", ["baseline", "policy"])
def test_nonrepair_arms_have_the_same_total_coding_ceiling(tmp_path, condition):
    result, calls, _ = run_case(tmp_path, condition=condition)
    assert len(calls) == 1
    assert calls[0]["iterations"] == 120
    assert calls[0]["timeout"] == 600
    assert result["external_repairs"] == 0


def test_time_ceiling_stops_repairs_without_resetting_budget(tmp_path):
    result, calls, phases = run_case(tmp_path, seconds=600)
    assert len(calls) == 1
    assert result["status"] == "budget_exhausted"
    assert result["external_repairs"] == 0
    assert phases == ["development"]


def test_total_iteration_ceiling_clips_calls(tmp_path):
    budget = default_budget(3)
    budget["max_iterations"] = 65
    result, calls, _ = run_case(tmp_path, budget=budget)
    assert [c["iterations"] for c in calls] == [60, 5]
    assert result["allocated_iterations"] == 65
    assert result["status"] == "budget_exhausted"



@pytest.mark.parametrize("limit", [-1, 11, True, 1.5])
def test_invalid_repair_limits_rejected(limit):
    with pytest.raises(ValueError):
        default_budget(limit)


@pytest.mark.parametrize("failed", [True, False])
def test_guidance_audit_preserves_mcp_response_without_accepting_errors(tmp_path, monkeypatch, failed):
    from harness.benchmarks.pilot import select_guidance
    from policy_selector import client
    response = ({"isError": True, "content": [{"type": "text", "text": "Evidence mismatch"}]}
                if failed else {"selected": [{"policy_id": "test"}]})

    async def request(*args):
        return response

    monkeypatch.setattr(client, "request", request)
    snapshot = RepositorySnapshot((("target.c", b"// <MASK>\n", 0o644),))
    task = {"target": "target.c", "request": "Complete the target"}
    path = tmp_path / "response.json"
    if failed:
        with pytest.raises(ValueError, match="selection unavailable"):
            select_guidance(task, snapshot, response_path=path)
    else:
        assert select_guidance(task, snapshot, response_path=path) == response
    assert json.loads(path.read_text()) == response


def test_freeze_records_one_repair_and_file_delivery(tmp_path, monkeypatch):
    from harness.benchmarks import pilot

    class Benchmark:
        evaluator_revision = "benchmark-v1"
        task_ids = ("t",)
        evaluation_limits = {
            "development_seconds": 1200,
            "final_build_seconds": 1200,
            "final_exploit_seconds": 60,
        }
        evaluation_resources = {
            "memory": "8g",
            "memory_swap": "8g",
            "cpus": 4,
            "pids_limit": 1024,
        }
        metadata = {"t": {"project_name": "file"}}

        def task(self, task_id):
            return {"id": task_id, "project": "file", "image": "fixture-image"}

    monkeypatch.setattr(pilot.subprocess, "check_output", lambda *a, **k: "sha256:test-image\n")
    root = tmp_path / "protocol"
    protocol = pilot.freeze(Benchmark(), root, ["t"])
    assert protocol["version"] == 3
    assert protocol["budget"] == default_budget(1)
    assert protocol["policy_delivery"]["path"] == POLICY_FILE
    assert pilot.load_protocol(root) == protocol
    selected = pilot.freeze(Benchmark(), tmp_path / "subset", ["t"], conditions=("policy", "verification", "full"))
    assert {r["condition"] for r in selected["runs"]} == {"policy", "verification", "full"}
    with pytest.raises(ValueError):
        pilot.freeze(Benchmark(), tmp_path / "invalid", ["t"], conditions=("policy", "policy"))


def test_supervisor_passes_external_policy_directory_to_worker(tmp_path, monkeypatch):
    from harness.adapters.repository import RepositoryAgent
    from harness.adapters import repository
    control = tmp_path / "policy"
    control.mkdir()
    (control / "policy.json").write_text('{}')
    requests = []

    class Process:
        def __init__(self, args, **kwargs):
            request = json.loads(Path(args[-1]).read_text())
            requests.append(request)
            sdk = Path(request["output"])
            sdk.mkdir()
            (sdk / "result.json").write_text('{"execution_status": "finished"}')

        def wait(self, **kwargs):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(repository.subprocess, "Popen", Process)
    monkeypatch.setattr(repository.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))
    result = RepositoryAgent("unused-python").run(tmp_path, tmp_path / "agent", "read policy", control=control)
    assert requests[0]["control"] == str(control.resolve())
    assert result["status"] == "ok"


def test_agent_shell_recovers_limits_but_not_unrelated_errors():
    from harness.adapters.repository import execute_repository_command

    class Box:
        restarted = False

        def execute(self, command, timeout):
            raise TimeoutError("bounded output")

        def restart(self):
            self.restarted = True

    box = Box()
    result = execute_repository_command(box, "noisy command")
    assert box.restarted
    assert result["exit_code"] == 124
    assert result["sandbox_restarted"] is True
    assert "/workspace" in result["output"]

    def failed_restart():
        raise RuntimeError("cleanup or recreation failed")
    box.restart = failed_restart
    with pytest.raises(RuntimeError):
        execute_repository_command(box, "noisy command")


@pytest.mark.skipif(os.getenv("PECA_TEST_DOCKER") != "1", reason="requires Docker")
def test_policy_file_is_readable_readonly_and_outside_candidate_workspace(tmp_path):
    control, work = tmp_path / "policy", tmp_path / "work"
    control.mkdir()
    work.mkdir()
    (control / "policy.json").write_text('{"selected": []}')
    with Sandbox(workspace=work, control=control) as box:
        assert box.execute(f"cat {POLICY_FILE}")["output"] == '{"selected": []}'
        assert box.execute(f"echo changed > {POLICY_FILE}")["exit_code"] != 0
        assert box.execute("test ! -e /workspace/policy.json")["exit_code"] == 0
    assert (control / "policy.json").read_text() == '{"selected": []}'


@pytest.mark.skipif(os.getenv("PECA_TEST_DOCKER") != "1", reason="requires Docker")
def test_output_overflow_restarts_container_and_preserves_workspace_and_policy(tmp_path):
    from harness.adapters.repository import execute_repository_command
    control, work = tmp_path / "policy", tmp_path / "work"
    control.mkdir()
    work.mkdir()
    (control / "policy.json").write_text('{"selected": []}')
    (work / "saved.c").write_text('int saved;')
    with Sandbox(workspace=work, control=control) as box:
        box.execute("echo ephemeral > /tmp/peca-restart-sentinel")
        result = execute_repository_command(box, "python3 -c 'print(\"x\" * 2100000)'")
        assert result["sandbox_restarted"] is True
        assert not box.closed
        assert box.execute("cat /workspace/saved.c")["output"] == 'int saved;'
        assert box.execute(f"cat {POLICY_FILE}")["output"] == '{"selected": []}'
        assert box.execute("test ! -e /tmp/peca-restart-sentinel")["exit_code"] == 0
        assert box.execute(f"echo changed > {POLICY_FILE}")["exit_code"] != 0
    assert box.closed
