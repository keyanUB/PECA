"""Summarize a completed frozen comparison without running code or calling models."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

from harness.contracts import Candidate, TaskSpec
from harness.experiments.simple import POLICY_PREFIX, REPAIR_PREFIX, load_manifest, summarize


ARMS = ("baseline", "policy", "verification", "full")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(root):
    manifest = load_manifest(root)
    plan = manifest["protocol"]
    results = json.loads((root / "results.json").read_text())
    expected = plan["runs"]
    if len(results) != len(expected) or [r["run_id"] for r in results] != [r["run_id"] for r in expected]:
        raise ValueError("Comparison is incomplete or does not match its frozen schedule")
    frozen = json.loads((root / "candidates-frozen.json").read_text())
    if len(frozen) != len(results) or len({r["run_id"] for r in frozen}) != len(results):
        raise ValueError("Missing or duplicate candidate-freeze records")
    frozen = {r["run_id"]: r for r in frozen}
    tasks = {t["id"]: t for t in plan["tasks"]}
    details = []
    raw_hashes = {name: digest(root / name) for name in ("execution.json", "results.json", "candidates-frozen.json")}
    for original, scheduled in zip(results, expected):
        if any(original.get(k) != v for k, v in scheduled.items()):
            raise ValueError("Run identity changed")
        run = root / "runs" / original["run_id"]
        task_data = tasks[original["task_id"]]
        task = TaskSpec(task_data["id"], task_data["family"], task_data["request"], "simple-design-v1")
        entry = {k: original.get(k) for k in ("run_id", "task_id", "repetition", "condition", "status", "candidate_sha256", "agent_seconds", "external_repairs")}
        entry.update(final_healthy=False, functional_pass=False, security_pass=False, joint_pass=False,
                     sdk_cost_estimate=0.0, sdk_cost_missing_calls=0, agent_calls=len(original.get("rounds", [])),
                     sdk_step_calls=0, sdk_steps_missing_calls=0, sdk_prompt_tokens=0, sdk_completion_tokens=0,
                     sdk_usage_missing_calls=0, development=[], regressions=[], final_failures=[])
        base_prompt = task.request + "\n\n" + plan["common_instructions"]
        if original["condition"] in ("policy", "full"):
            advice = json.loads((root / "guidance" / f"{task.task_id}-r{original['repetition']}.json").read_text())["response"]
            if advice is not None:
                base_prompt += POLICY_PREFIX + json.dumps(advice, sort_keys=True)
            elif original["status"] != "advisor_error":
                raise ValueError("Failed policy selection silently became a coding run")
        repair_arm = original["condition"] in ("verification", "full")
        if original["external_repairs"] > int(repair_arm):
            raise ValueError("Unexpected external repair call")
        if original.get("candidate_sha256") != frozen[original["run_id"]].get("candidate_sha256") or original["status"] != frozen[original["run_id"]]["status"]:
            raise ValueError("Final candidate/status differs from the pre-scoring freeze")
        for index, round_ in enumerate(original.get("rounds", [])):
            expected_prompt = base_prompt
            if index:
                feedback = json.loads((run / "feedback.json").read_text())
                previous = original["rounds"][index - 1]
                if feedback["candidate_sha256"] != previous["candidate_sha256"]:
                    raise ValueError("Repair feedback candidate mismatch")
                if {f["check_id"] for f in feedback["failures"]} != set(previous["development"]["failed_checks"]):
                    raise ValueError("Repair feedback does not match development failures")
                expected_prompt += REPAIR_PREFIX + json.dumps(feedback, sort_keys=True)
            prompt_path = run / f"prompt-{index}.txt"
            if prompt_path.read_text() != expected_prompt:
                raise ValueError("Prompt differs from the frozen treatment or feedback")
            raw_hashes[str(prompt_path.relative_to(root))] = digest(prompt_path)
            expected_iterations = (plan["budget"]["repair_arm_initial_iterations"] if index == 0 else plan["budget"]["repair_call_max_iterations"]) if repair_arm else plan["budget"]["sdk_iterations_per_run"]
            if round_["budget"]["iterations"] != expected_iterations:
                raise ValueError("SDK iteration allocation changed")
            agent = round_["agent"]
            sdk = agent.get("sdk", {})
            metrics = sdk.get("metrics", {})
            if metrics.get("accumulated_cost") is None:
                entry["sdk_cost_missing_calls"] += 1
            else:
                entry["sdk_cost_estimate"] += metrics["accumulated_cost"]
            if sdk.get("agent_step_calls") is None:
                entry["sdk_steps_missing_calls"] += 1
            else:
                entry["sdk_step_calls"] += sdk["agent_step_calls"]
            usage = metrics.get("accumulated_token_usage")
            if usage is None:
                entry["sdk_usage_missing_calls"] += 1
            else:
                entry["sdk_prompt_tokens"] += usage.get("prompt_tokens", 0)
                entry["sdk_completion_tokens"] += usage.get("completion_tokens", 0)
            if "development" in round_:
                candidate = Candidate.from_file(task.task_id, run / round_["candidate_file"])
                report_path = run / f"development-{index}/report.json"
                report = json.loads(report_path.read_text())
                raw_hashes[str(report_path.relative_to(root))] = digest(report_path)
                current = summarize(report, task, candidate, "development", manifest["verifier_image"])
                if current != round_["development"]:
                    raise ValueError("Saved development summary differs from raw evidence")
                entry["development"].append(current)
        if "final" in original:
            candidate = Candidate.from_file(task.task_id, run / original["final_candidate"])
            if candidate.sha256 != original["candidate_sha256"]:
                raise ValueError("Candidate bytes changed")
            report_path = run / "final-evaluation/report.json"
            raw_hashes[str(report_path.relative_to(root))] = digest(report_path)
            current = summarize(json.loads(report_path.read_text()), task, candidate, "final", manifest["verifier_image"])
            if current != original["final"]:
                raise ValueError("Saved final summary differs from raw evidence")
            entry.update(final_healthy=current["healthy"], functional_pass=current["functional_pass"],
                         security_pass=current["security_pass"], final_failures=current["failed_checks"])
            entry["joint_pass"] = original["status"] == "completed" and current["status"] == "passed"
        if entry["joint_pass"] != original["joint_pass"]:
            raise ValueError("Primary outcome does not recompute")
        dev = entry["development"]
        entry["repair_succeeded"] = bool(entry["external_repairs"] and dev and dev[-1]["status"] == "passed" and entry["status"] == "completed")
        if len(dev) > 1 and dev[0]["healthy"] and dev[-1]["healthy"]:
            entry["regressions"] = sorted(set(dev[-1]["failed_checks"]) - set(dev[0]["failed_checks"]))
        entry["verification_seconds"] = sum(r.get("verification_seconds", 0) for r in original.get("rounds", [])) + original.get("final_verification_seconds", 0)
        details.append(entry)

    guidance = []
    expected_guidance = {f"{r['task_id']}-r{r['repetition']}.json" for r in expected if r['condition'] in ('policy', 'full')}
    paths = list((root / "guidance").glob("*.json"))
    if {p.name for p in paths} != expected_guidance:
        raise ValueError("Cached guidance slots do not match the design")
    for path in sorted(paths):
        raw_hashes[str(path.relative_to(root))] = digest(path)
        record = json.loads(path.read_text())
        response = record.get("response")
        entry = {"id": path.stem, "elapsed_seconds": record["elapsed_seconds"], "error": record.get("error"),
                 "selected": [], "input_tokens": 0, "output_tokens": 0, "usage_complete": bool(response)}
        if response is not None:
            entry["selected"] = [{k: p.get(k) for k in ("policy_id", "guidance", "rationale", "assessment")} for p in response["selected"]]
            entry["model"] = response.get("response_model", response.get("model"))
            attempts = response.get("attempts") or [{"usage": response.get("usage")}]
            entry["attempts"] = len(attempts)
            for attempt in attempts:
                usage = attempt.get("usage")
                if usage is None:
                    entry["usage_complete"] = False
                else:
                    entry["input_tokens"] += usage.get("input_tokens", 0)
                    entry["output_tokens"] += usage.get("output_tokens", 0)
        guidance.append(entry)

    def aggregate(rows):
        return {"planned": len(rows), "completed": sum(r["status"] == "completed" for r in rows),
                "final_healthy": sum(r["final_healthy"] for r in rows),
                "completed_functional_pass": sum(r["status"] == "completed" and r["functional_pass"] for r in rows),
                "completed_security_pass": sum(r["status"] == "completed" and r["security_pass"] for r in rows),
                "joint_pass": sum(r["joint_pass"] for r in rows),
                "statuses": dict(Counter(r["status"] for r in rows)),
                "repairs": sum(r["external_repairs"] for r in rows), "successful_repairs": sum(r["repair_succeeded"] for r in rows),
                "regressing_runs": sum(bool(r["regressions"]) for r in rows),
                "agent_seconds": sum(r["agent_seconds"] for r in rows),
                "median_agent_seconds": statistics.median(r["agent_seconds"] for r in rows),
                **{k: sum(r[k] for r in rows) for k in ("agent_calls", "sdk_step_calls", "sdk_steps_missing_calls", "sdk_cost_estimate", "sdk_cost_missing_calls", "sdk_prompt_tokens", "sdk_completion_tokens", "sdk_usage_missing_calls", "verification_seconds")}}

    arms = {arm: aggregate([r for r in details if r["condition"] == arm]) for arm in ARMS}
    by_task = {task: {arm: aggregate([r for r in details if r["task_id"] == task and r["condition"] == arm]) for arm in ARMS} for task in tasks}
    paired = {(r["task_id"], r["repetition"], r["condition"]): r for r in details}
    contrasts = []
    for treatment, control in plan["contrasts"]:
        wins = losses = ties = 0
        for task in tasks:
            for repetition in range(1, plan["repetitions"] + 1):
                difference = int(paired[task, repetition, treatment]["joint_pass"]) - int(paired[task, repetition, control]["joint_pass"])
                wins += difference > 0
                losses += difference < 0
                ties += difference == 0
        contrasts.append({"treatment": treatment, "control": control, "wins": wins, "losses": losses, "ties": ties,
                          "joint_success_difference_pp": (wins - losses) / (wins + losses + ties) * 100})
    return {"execution_sha256": digest(root / "execution.json"), "protocol_sha256": manifest["protocol_sha256"],
            "coding_model": plan["coding_model"], "advisor_model": plan["advisor_model"], "ast_context": plan["ast_context"],
            "analyzer_sha256": digest(Path(__file__)), "input_sha256": raw_hashes,
            "arms": arms, "by_task": by_task, "contrasts": contrasts, "runs": details, "guidance": guidance,
            "coding_cost_estimate": sum(r["sdk_cost_estimate"] for r in details),
            "advisor_unique_input_tokens": sum(g["input_tokens"] for g in guidance),
            "advisor_unique_output_tokens": sum(g["output_tokens"] for g in guidance),
            "advisor_unique_seconds": sum(g["elapsed_seconds"] for g in guidance),
            "advisor_usage_missing_slots": sum(not g["usage_complete"] for g in guidance),
            "advisor_cost_estimate": None,
            "limitations": ["Three familiar Python development tasks; three repetitions each; no significance or general security claim",
                            "Final tests withhold input combinations, not entire vulnerability classes or repositories",
                            "Equal iteration/runtime ceilings do not equal realized cost; repair also changes conversation staging",
                            "Advisor results are cached/shared within each task/repetition; pair outcomes are correlated",
                            "SDK costs are estimates; missing usage is unknown rather than zero; advisor dollars are not estimated"]}


def markdown(result, artifact):
    lines = ["# Simpler-design comparison", "", "Completed 36 scheduled runs: three tasks × three repetitions × four conditions. AST was disabled.",
             f"Coding model: `{result['coding_model']}`. Policy advisor: `{result['advisor_model']}`.",
             "Final scores were computed after generation and repair finished. All primary outcomes below were recomputed from candidate-bound verifier reports.", "",
             "## Outcomes", "", "All outcome columns use nine planned slots per condition. Functional/security columns also require the agent to finish; incomplete candidates remain diagnostic.", "",
             "| Condition | Finished | Functional | Security | Joint success | Repairs / successful | SDK coding cost |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for arm, a in result["arms"].items():
        lines.append(f"| {arm} | {a['completed']}/9 | {a['completed_functional_pass']}/9 | {a['completed_security_pass']}/9 | {a['joint_pass']}/9 | {a['repairs']} / {a['successful_repairs']} | ${a['sdk_cost_estimate']:.4f} |")
    lines += ["", "## Joint success by task", "", "| Task | Baseline | Policy | Verification | Full |", "| --- | ---: | ---: | ---: | ---: |"]
    for task, arms in result["by_task"].items():
        lines.append("| " + task + " | " + " | ".join(f"{arms[a]['joint_pass']}/3" for a in ARMS) + " |")
    lines += ["", "## Paired comparisons", "", "| Treatment minus control | Wins | Losses | Ties | Joint difference |", "| --- | ---: | ---: | ---: | ---: |"]
    for c in result["contrasts"]:
        lines.append(f"| {c['treatment']} − {c['control']} | {c['wins']} | {c['losses']} | {c['ties']} | {c['joint_success_difference_pp']:+.1f} pp |")
    lines += ["", "These are descriptive differences across nine task/repetition pairs, not statistical significance estimates.", "",
              "## Failures and incomplete work", "", "| Run | Agent status | Final failed checks |", "| --- | --- | --- |"]
    for r in result["runs"]:
        if not r["joint_pass"]:
            failures = ", ".join(r["final_failures"]) or ("Checks passed; agent did not finish" if r["final_healthy"] else "Evaluation unavailable")
            lines.append(f"| {r['run_id']} | {r['status']} | {failures} |")
    if all(r["joint_pass"] for r in result["runs"]):
        lines.append("| None | All finished | All final checks passed |")
    lines += ["", "## Resource use", "", f"SDK-reported coding cost totals **${result['coding_cost_estimate']:.4f}**, excluding advisor charges.",
              f"The nine cached advisor slots used {result['advisor_unique_input_tokens']:,} recorded input tokens and {result['advisor_unique_output_tokens']:,} output tokens across their recorded attempts.",
              f"Advisor time totalled {result['advisor_unique_seconds']:.1f} seconds. Missing advisor usage slots: {result['advisor_usage_missing_slots']}.",
              "Each policy-bearing arm would incur those advisor tokens independently without sharing; actual cached requests were charged only once per pair. Advisor dollar cost is unknown.", "",
              "| Condition | Agent time | Median/run | Verifier time | Missing SDK cost calls |", "| --- | ---: | ---: | ---: | ---: |"]
    for arm, a in result["arms"].items():
        lines.append(f"| {arm} | {a['agent_seconds']:.1f}s | {a['median_agent_seconds']:.1f}s | {a['verification_seconds']:.1f}s | {a['sdk_cost_missing_calls']} |")
    lines += ["", "## Scope and evidence", "", *["- " + item for item in result["limitations"]], "",
              f"Local artifacts: `{artifact}`. Machine-readable analysis, source/check hashes, per-run traces and candidate files remain there.",
              f"Execution manifest SHA-256: `{result['execution_sha256']}`.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.directory.resolve())
    (args.directory / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.report.write_text(markdown(result, str(args.directory)))
    print(json.dumps({"arms": result["arms"], "contrasts": result["contrasts"]}, indent=2))


if __name__ == "__main__":
    main()
