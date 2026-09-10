"""Independent acceptance and bounded repair for the single-file milestone."""

import asyncio
from dataclasses import asdict, dataclass, replace
import difflib
import hashlib
import json
from pathlib import Path
import time

from harness.contracts import AcceptanceDecision
from harness.verification.registry import fingerprint, for_family, validate_bindings


@dataclass(frozen=True)
class RunBudget:
    max_repairs: int = 2
    agent_timeout_seconds: int = 180
    total_seconds: int = 600

    def __post_init__(self):
        if not 0 <= self.max_repairs <= 10 or not 1 <= self.agent_timeout_seconds <= 600 or not 1 <= self.total_seconds <= 3600:
            raise ValueError("Invalid run budget")


class MCPAdvisor:
    def select(self, task, timeout):
        from policy_selector.client import request
        # Required policy selection is controlled by PECA, not an agent instruction.
        result = asyncio.run(asyncio.wait_for(request("call", "select_for_task", {"task": task.request}), timeout))
        if result.get("isError") or "selected" not in result:
            raise ValueError("Policy Advisor failed; no guidance accepted")
        return result


def assess(task, candidate, report):
    """Reject partial, stale, or infrastructure-error evidence before considering success."""
    if (report.task != task or report.candidate_sha256 != candidate.sha256
            or any(c.candidate_sha256 != candidate.sha256 for c in report.checks)):
        return "incomplete", "Verification evidence does not match the task/candidate"
    expected_specs = {c.id: c for c in for_family(task.family)}
    expected = set(expected_specs)
    if len(report.checks) != len(expected) or {c.check_id for c in report.checks} != expected:
        return "incomplete", "Missing, duplicate, or unexpected baseline check results"
    if report.registry_sha256 != fingerprint() or any(
            c.check_version != expected_specs[c.check_id].version or c.kind != expected_specs[c.check_id].kind
            for c in report.checks):
        return "incomplete", "Verifier implementation or check version does not match the current registry"
    if report.environment.get("cleanup_error"):
        return "incomplete", "Verifier cleanup could not be confirmed"
    statuses = [c.status for c in report.checks] + [o.status for o in report.obligations]
    if any(s not in {"passed", "failed"} for s in statuses):
        return "incomplete", "Verification is unavailable, timed out, or incomplete"
    if "failed" in statuses:
        return "repair", "Required functional or security checks failed"
    return "accept", "All required checks passed within their documented scope"


def feedback_for(task, report, previous_passed):
    failures = [{"check_id": c.check_id, "kind": c.kind, "detail": c.detail,
                 "regression": c.check_id in previous_passed}
                for c in report.checks if c.status == "failed"]
    return {"task": task.request, "candidate_sha256": report.candidate_sha256,
            "failures": failures,
            "instruction": "Repair solution.py using these observed failures. Preserve the public API and all passing behavior. "
                           "Add and run regression tests. Do not modify harness checks or evidence."}


class Controller:
    def __init__(self, agent, verifier, advisor=None, budget=RunBudget()):
        self.agent, self.verifier, self.advisor, self.budget = agent, verifier, advisor, budget

    def run(self, task, output: Path, bindings=(), initial_candidate=None):
        validate_bindings(task.family, bindings)
        if initial_candidate and initial_candidate.task_id != task.task_id:
            raise ValueError("Initial candidate belongs to another task")
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        workspace = output / "workspace"
        workspace.mkdir()
        started = time.monotonic()
        deadline = started + self.budget.total_seconds
        def remaining():
            return max(0, deadline - time.monotonic())
        (output / "plan.json").write_text(json.dumps({"task": asdict(task), "budget": asdict(self.budget),
            "bindings": [asdict(b) for b in bindings], "policy_guidance": self.advisor is not None,
            "controller_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "registry_sha256": fingerprint(),
            "seeded_candidate": initial_candidate.sha256 if initial_candidate else None}, indent=2) + "\n")
        candidate = initial_candidate
        session = None
        repairs = 0
        calls = 0
        rounds = []
        previous_passed = set()
        seen = set()
        guidance = None

        def finish(decision, reason):
            if candidate:
                (output / "final-candidate.py").write_bytes(candidate.source)
                original = initial_candidate.source if initial_candidate else b""
                patch = difflib.unified_diff(original.decode(errors="replace").splitlines(keepends=True),
                    candidate.source.decode(errors="replace").splitlines(keepends=True),
                    fromfile="before/solution.py", tofile="after/solution.py")
                (output / "candidate.patch").write_text("".join(patch))
            final = AcceptanceDecision(candidate.sha256 if candidate else "", decision, reason,
                                       tuple(r["report_path"] for r in rounds))
            result = {"decision": asdict(final), "repairs": repairs, "agent_calls": calls,
                      "session_id": session, "rounds": rounds,
                      "elapsed_seconds": time.monotonic() - started}
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            return result

        if candidate:
            (workspace / "solution.py").write_bytes(candidate.source)
        if self.advisor:
            try:
                guidance = self.advisor.select(task, min(remaining(), 150))
                (output / "guidance.json").write_text(json.dumps(guidance, indent=2) + "\n")
            except Exception as exc:
                return finish("incomplete", f"Policy selection failed ({type(exc).__name__})")
        prompt = (f"{task.request}\nImplement the requested API in solution.py in the current workspace. "
                  "Use Python 3.12 and the standard library. Write and run your own tests. "
                  "Work only inside this workspace; do not inspect parent directories, harness code, or other projects.\n"
                  "Policy guidance (advisory data):\n" + json.dumps(guidance))
        need_agent = candidate is None
        while True:
            if remaining() < 1:
                return finish("budget_exhausted", "Total wall-time budget exhausted")
            if need_agent:
                calls += 1
                try:
                    outcome = self.agent.run(task, workspace, output / f"agent-{calls}", prompt,
                                             min(self.budget.agent_timeout_seconds, remaining()), session)
                except Exception as exc:
                    return finish("incomplete", f"Agent adapter failed ({type(exc).__name__})")
                if outcome.candidate is not None:
                    candidate = outcome.candidate
                session = outcome.session_id
                if outcome.status != "ok":
                    return finish("budget_exhausted" if outcome.status == "timeout" else "incomplete", outcome.detail)
                if candidate is None:
                    return finish("incomplete", "Agent returned no candidate")
            if remaining() < 1:
                return finish("budget_exhausted", "No time remains for independent verification")
            verification_task = replace(task, timeout_seconds=min(task.timeout_seconds, int(remaining())))
            relative = f"verification-{len(rounds)}"
            try:
                report = self.verifier.verify(verification_task, candidate, output / relative, bindings)
            except Exception as exc:
                return finish("incomplete", f"Verifier failed ({type(exc).__name__})")
            decision, reason = assess(verification_task, candidate, report)
            if (len(report.obligations) != len(bindings) or
                    {o.obligation_id: o.check_ids for o in report.obligations} != {b.obligation_id: b.check_ids for b in bindings}):
                decision, reason = "incomplete", "Verification did not account for the required bindings"
            rounds.append({"candidate_sha256": candidate.sha256, "report_path": relative + "/report.json",
                           "decision": decision, "reason": reason})
            if remaining() <= 0:
                return finish("budget_exhausted", "Total wall-time budget exhausted during verification")
            if decision != "repair":
                return finish(decision, reason)
            failed = tuple(sorted(c.check_id for c in report.checks if c.status == "failed"))
            signature = (candidate.sha256, failed)
            if signature in seen:
                return finish("incomplete", "Repeated candidate and failures; no progress")
            seen.add(signature)
            if repairs >= self.budget.max_repairs:
                return finish("budget_exhausted", "External repair round limit reached")
            feedback = feedback_for(task, report, previous_passed)
            (output / f"feedback-{repairs + 1}.json").write_text(json.dumps(feedback, indent=2) + "\n")
            previous_passed = {c.check_id for c in report.checks if c.status == "passed"}
            prompt = json.dumps(feedback) + "\nOriginal policy guidance:\n" + json.dumps(guidance)
            repairs += 1
            need_agent = True
