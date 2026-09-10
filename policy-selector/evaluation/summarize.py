"""Summarize the fixed pilot without counting missing code as secure or insecure."""

import argparse
import json
from pathlib import Path
from statistics import median

from cases import TASKS
from compare import events_from
from policy_selector.catalog import Catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    catalog = Catalog()
    rows = []
    for result_path in sorted(root.glob("*/result.json")):
        result = json.loads(result_path.read_text())
        trace = events_from(result_path.parent / "trace.log")
        actions = {e["tool_call_id"]: e for e in trace if e.get("kind") == "ActionEvent" and e.get("action")}
        audit = []
        for event in trace:
            if event.get("kind") != "ObservationEvent" or event.get("tool_name") != "select_for_task":
                continue
            observation = event["observation"]
            if observation.get("is_error"):
                continue
            selection = next(json.loads(c["text"]) for c in observation["content"]
                             if c.get("text", "").startswith("{"))
            actual_task = actions[event["tool_call_id"]]["action"]["data"]["task"]
            audit.append({
                "response_id": selection["response_id"], "model": selection["response_model"],
                "exact_task": actual_task == TASKS[result["task"]],
                "canonical_policy_text": all(p["policy"] == catalog.policies[p["policy_id"]].model_dump()
                                             for p in selection["selected"]),
                "exact_evidence": all(e["source"] == "task" and e["quote"] in actual_task
                                      for p in selection["selected"] for e in p["evidence"]),
                "policies": [{"id": p["policy_id"], "category": p["policy"]["category"],
                              "rationale": p["rationale"], "guidance": p["guidance"]}
                             for p in selection["selected"]],
                "attempts": len(selection.get("attempts", [])),
            })
        result["selector_audit"] = audit
        result["agent_argument_errors"] = sum(e.get("kind") == "AgentErrorEvent" for e in trace)
        result["mcp_argument_errors"] = sum(
            e.get("kind") == "AgentErrorEvent" and e.get("tool_name") in
            {"select_for_task", "select_for_repository", "refine_selection", "policy_catalog"}
            for e in trace)
        result["agent_errors_by_tool"] = {}
        for event in trace:
            if event.get("kind") == "AgentErrorEvent":
                name = event.get("tool_name", "unknown")
                result["agent_errors_by_tool"][name] = result["agent_errors_by_tool"].get(name, 0) + 1
        evaluation = result["evaluation"]
        result["code_evaluable"] = "tests" in evaluation
        result["functional_success"] = result["code_evaluable"] and evaluation["functional_passed"] == evaluation["functional_total"]
        result["security_success"] = result["code_evaluable"] and evaluation["security_passed"] == evaluation["security_total"]
        result["joint_success"] = (result["functional_success"] and result["security_success"]
                                   and result["treatment_compliant"] and not result["timed_out"])
        result["exact_selection_task_compliant"] = (
            bool(audit) and all(a["exact_task"] for a in audit)) if result["arm"] == "scp" else not audit
        result["strict_joint_success"] = result["joint_success"] and result["exact_selection_task_compliant"]
        rows.append(result)
    aggregate = {}
    for arm in ("baseline", "scp"):
        subset = [r for r in rows if r["arm"] == arm]
        aggregate[arm] = {
            "runs": len(subset), "evaluable": sum(r["code_evaluable"] for r in subset),
            "joint_success": sum(r["joint_success"] for r in subset),
            "exact_selection_task_compliant": sum(r["exact_selection_task_compliant"] for r in subset),
            "strict_joint_success": sum(r["strict_joint_success"] for r in subset),
            "functional_passed": sum(r["evaluation"].get("functional_passed", 0) for r in subset),
            "functional_total_on_evaluable": sum(r["evaluation"].get("functional_total", 0) for r in subset),
            "security_passed": sum(r["evaluation"].get("security_passed", 0) for r in subset),
            "security_total_on_evaluable": sum(r["evaluation"].get("security_total", 0) for r in subset),
            "median_seconds": median(r["elapsed_seconds"] for r in subset) if subset else None,
        }
    summary = {"aggregate": aggregate, "runs": rows}
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(aggregate, indent=2))
    for row in rows:
        print(row["task"], row["repetition"], row["arm"], "joint_success", row["joint_success"],
              "agent_errors", row["agent_argument_errors"], "mcp_errors", row["mcp_argument_errors"])


if __name__ == "__main__":
    main()
