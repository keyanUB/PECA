"""Export compact, shareable diagnostics without raw prompts or model traces."""
import argparse
import hashlib
import json
from pathlib import Path

from harness.conditions import CONDITION_LABELS, condition_label


def summarize(root):
    protocol_bytes = (root / "protocol.json").read_bytes()
    digest = hashlib.sha256(protocol_bytes).hexdigest()
    if digest != (root / "protocol.sha256").read_text().strip():
        raise ValueError("Protocol digest mismatch")
    protocol = json.loads(protocol_bytes)
    rows = []
    for planned in protocol["runs"]:
        task_id, condition = planned["task_id"], planned["condition"]
        path = root / task_id / condition / "result.json"
        if not path.exists():
            raise ValueError(f"Pilot incomplete: missing {task_id}/{condition}")
        result = json.loads(path.read_text())
        qualification = json.loads((root / task_id / "qualification.json").read_text())
        rounds = result.get("rounds", [])
        metrics = [r["agent"].get("sdk", {}).get("metrics", {}) for r in rounds]
        missing_costs = sum(m.get("accumulated_cost") is None for m in metrics)
        rows.append({"task_id": task_id, "condition": condition, "status": result["status"],
                     "qualified": qualification["qualified"],
                     "developer_status": rounds[-1]["development"]["status"] if rounds else "unavailable",
                     "hidden_status": result.get("hidden_final", {}).get("status", "unavailable"),
                     "candidate_sha256": rounds[-1]["candidate_sha256"] if rounds else None,
                     "joint_pass": result.get("joint_pass", False) if qualification["qualified"] else None,
                     "external_repairs": result.get("external_repairs", 0),
                     "external_repair_enabled": result.get("external_repair_enabled", False),
                     "policy_delivery_complete": result.get('policy_delivery_complete'),
                     "policy_delivery_rounds": [r.get('policy_delivery') for r in rounds],
                     "iteration_allocations": [r.get("budget", {}).get("iterations") for r in rounds],
                     "iterations_used": [r["agent"].get("sdk", {}).get("agent_step_calls") for r in rounds],
                     "agent_seconds": round(result.get("agent_seconds", 0), 2),
                     "cleanup_confirmed": all(r["agent"].get("cleanup_confirmed", False) for r in rounds) if rounds else None,
                     "sdk_estimated_cost_usd": None if missing_costs else sum(m["accumulated_cost"] for m in metrics),
                     "sdk_recorded_cost_usd": sum(m.get("accumulated_cost") or 0 for m in metrics),
                     "calls_missing_cost": missing_costs,
                     "prompt_tokens": sum(m.get("accumulated_token_usage", {}).get("prompt_tokens", 0) for m in metrics),
                     "completion_tokens": sum(m.get("accumulated_token_usage", {}).get("completion_tokens", 0) for m in metrics),
                     "changed_files": [r["path"] for r in rounds[-1]["changed_files"]] if rounds else []})
    guidance, guidance_errors = {}, {}
    for task in protocol["tasks"]:
        path = root / task["id"] / "guidance.json"
        if path.exists():
            g = json.loads(path.read_text())
            guidance[task["id"]] = {"model": g["model"], "response_model": g.get("response_model"),
                "selected_ids": [s["policy_id"] for s in g["selected"]], "usage": g.get("usage"),
                "attempts": g.get("attempts"),
                "coverage": g["coverage"], "obligations": g.get("obligations", [])}
        error = root / task["id"] / "guidance-error.json"
        if error.exists():
            guidance_errors[task["id"]] = json.loads(error.read_text())
            raw = root / task["id"] / "guidance-response.json"
            if raw.exists():
                diagnostics = json.loads(raw.read_text()).get('diagnostics')
                if diagnostics is not None:
                    guidance_errors[task["id"]]['diagnostics'] = diagnostics
    summary = {"protocol_sha256": digest, "benchmark_revision": protocol["benchmark_revision"],
               "stage": protocol["stage"], "results": rows, "guidance": guidance,
               "guidance_errors": guidance_errors,
               "budget": protocol.get("budget"),
               "condition_labels": CONDITION_LABELS,
               "qualified_runs": sum(r["qualified"] for r in rows)}
    lines = ["# Repository pilot results", "", f"Protocol SHA-256: `{digest}`.", "",
             "These are development diagnostics. Unqualified runs have no joint security score.", "",
             "Advisor-only uses the stable condition ID `policy` in JSON and artifact paths.", "",
             "| Task | Condition | Agent | Developer suite | Hidden PoC | Qualified | Repairs | Complete policy exposure | Agent seconds |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in sorted(rows, key=lambda r: (int(r["task_id"]), r["condition"])):
        exposure = ('N/A' if r['condition'] not in ('policy', 'full') else 'Unrecorded'
                    if r['policy_delivery_complete'] is None else 'Yes' if r['policy_delivery_complete'] else 'No')
        lines.append(f"| {r['task_id']} | {condition_label(r['condition'])} | {r['status']} | {r['developer_status']} | {r['hidden_status']} | {'Yes' if r['qualified'] else 'No'} | {r['external_repairs']} | {exposure} | {r['agent_seconds']:.1f} |")
    cost = sum(r["sdk_recorded_cost_usd"] for r in rows)
    missing = sum(r["calls_missing_cost"] for r in rows)
    lines += ["", f"Recorded SDK-estimated coding-model cost: ${cost:.4f}; {missing} agent calls lack cost records. Advisor calls are excluded. This is not a provider billing statement.",
              "Advisor failures are operational failures; absent candidates have no functional or security-test outcome.",
              "Complete policy exposure is reported separately from code-test success. Missing exposure cannot support a claim about fully delivered guidance; it is not proof of attention or compliance.",
              "", "`incomplete` means the agent did not finish normally, even if its candidate passed a check.",
              "`build_failed` and `error` are not counted as demonstrated code vulnerabilities.",
              "Developer-suite pass is functional evidence; hidden-PoC pass has only the scope of that PoC.", ""]
    return summary, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New output basename; writes .json and .md")
    args = parser.parse_args()
    data, markdown = summarize(args.root)
    paths = [args.output.with_suffix(s) for s in (".json", ".md")]
    if any(p.exists() for p in paths):
        raise ValueError("Summary output already exists")
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(json.dumps(data, indent=2) + "\n")
    paths[1].write_text(markdown)


if __name__ == "__main__":
    main()
