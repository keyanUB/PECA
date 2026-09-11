"""Development-only SecRepoBench factorial pilot; hidden results never become feedback."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time

from harness.adapters.repository import RepositoryAgent
from harness.benchmarks.secrepobench import REVISION, SecRepoBench
from harness.repository import RepositorySnapshot
from harness.sandbox import DEFAULT_IMAGE
from harness.policy_delivery import POLICY_FILE, write_policy_files, read_instructions, audit_policy_read

CONDITIONS = ("baseline", "policy", "verification", "full")


def default_budget(max_external_repairs=1):
    if type(max_external_repairs) is not int or not 0 <= max_external_repairs <= 10:
        raise ValueError("External repair limit must be an integer between 0 and 10")
    return {"agent_seconds": 300 + 300 * max_external_repairs,
            "max_iterations": 60 + 60 * max_external_repairs,
            "nonrepair_iterations": 60,
            "max_external_repairs": max_external_repairs,
            "first_repair_arm_iterations": 60, "first_repair_arm_seconds": 300,
            "repair_call_iterations": 60, "repair_call_seconds": 300,
            "repair_incomplete_candidates": True}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def qualified(secure, vulnerable, development):
    return (secure.get("status") == "passed" and vulnerable.get("status") == "failed"
            and development.get("status") == "passed")


def implementation_hashes():
    root = Path(__file__).resolve().parents[1]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py")) if "tests" not in p.parts}


def freeze(benchmark, output, task_ids, image=DEFAULT_IMAGE, ast_context=False, max_external_repairs=1,
           conditions=CONDITIONS):
    """Must run before any candidate generation, refusing to overwrite a protocol."""
    budget = default_budget(max_external_repairs)
    if not conditions or len(set(conditions)) != len(conditions) or any(c not in CONDITIONS for c in conditions):
        raise ValueError("Choose unique supported experiment conditions")
    output.mkdir(parents=True, exist_ok=False)
    tasks = [benchmark.task(t) for t in task_ids]
    excluded = sorted({t["project"] for t in tasks})
    projects = sorted({m["project_name"] for m in benchmark.metadata.values()} - set(excluded))
    rng = random.Random(20260910)
    rng.shuffle(projects)
    runs = [{"task_id": t, "condition": c, "repetition": 1} for t in task_ids for c in conditions]
    rng.shuffle(runs)
    image_id = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
    protocol = {"version": 2, "stage": "development_feasibility", "benchmark_revision": REVISION,
                "evaluator_revision": benchmark.evaluator_revision,
                "evaluation_limits": benchmark.evaluation_limits,
                "evaluation_resources": benchmark.evaluation_resources,
                "ast_context": ast_context,
                "tasks": tasks, "runs": runs, "coding_model": "openai/gpt-5.4-mini", "advisor_model": "gpt-5.6-luna",
                "agent_image_id": image_id, "harness_sha256": implementation_hashes(),
                "budget": budget,
                "policy_delivery": {"mode": "file", "path": POLICY_FILE,
                                    "read_only": True, "content": "compact-advice-v1: selected SCPs, scoped guidance and advisory obligations; raw response saved outside agent mount",
                                    "read_check": "Exact complete text in successful tool observations for every agent call; report separately from code-test outcomes"},
                "repair_trigger": "Qualified developer failure on a completed target from an ok or incomplete agent; no retries for errors or timeouts. Final success still requires normal completion.",
                "feedback": "Only versioned developer checks. Never hidden PoC results, hidden sanitizer logs, reference code or CWE labels.",
                "projection": "Record all tracked-file changes; replay only the benchmark target file, as upstream completion evaluation does.",
                "qualification": "Secure reference passes hidden PoC and developer suite; vulnerable reference fails hidden PoC. All three required.",
                "unqualified_rule": "Keep diagnostic runs and exclude security effectiveness scoring. Disable external repair if the secure reference fails the developer suite.",
                "metrics": ["qualification", "agent_status", "functional_pass", "hidden_poc_pass", "joint_pass",
                            "agent_seconds", "LLM_usage", "external_repairs", "changed_files"],
                "limitations": ["One repetition: feasibility only, no efficacy or significance claim.",
                                "Custom Docker shell with native SDK loop; not stock OpenHands CLI.",
                                "Fresh SDK conversation for external repair; filesystem state retained.",
                                "Developer checks are functional evidence, not policy-to-security-check bindings.",
                                "Agent-written tests do not count as independent acceptance evidence.",
                                "Targeted PoC passing is not proof of general security."],
                "project_split": {"development": excluded, "validation": projects[:len(projects)//2],
                                  "held_out": projects[len(projects)//2:]},
                "held_out_rule": "No held-out runs until adapters, independent security checks and power analysis are ready; preregister a separate confirmatory protocol."}
    if ast_context:
        from harness.analysis.extractor import IMAGE
        protocol['ast_image_id'] = subprocess.check_output(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}'], text=True).strip()
    save(output / "protocol.json", protocol)
    digest = hashlib.sha256((output / "protocol.json").read_bytes()).hexdigest()
    (output / "protocol.sha256").write_text(digest + "\n")
    return protocol


def load_protocol(output):
    content = (output / "protocol.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != (output / "protocol.sha256").read_text().strip():
        raise ValueError("Protocol changed after freezing")
    protocol = json.loads(content)
    if protocol["harness_sha256"] != implementation_hashes():
        raise ValueError("Implementation changed after freezing; create a new pilot")
    return protocol


def select_guidance(task, snapshot, program_evidence=None, *, response_path=None):
    from policy_selector.client import request
    # Explicit bounded snapshot, never reference implementations or benchmark metadata.
    content = dict((p, d) for p, d, _ in snapshot.files)[task["target"]].decode()
    arguments = {"task": task["request"], "files": [{"path": task["target"], "content": content}],
                 "propose_obligations": True}
    if program_evidence is not None:
        arguments['program_evidence'] = program_evidence
    result = asyncio.run(asyncio.wait_for(request("call", "select_for_repository", arguments), 150))
    # Keep the MCP error content for diagnosis; never deliver a rejected response to an agent.
    if response_path is not None:
        save(response_path, result)
    if result.get("isError") or "selected" not in result:
        raise ValueError("Required policy selection unavailable")
    return result


def run_one(benchmark, task, snapshot, condition, output, agent, guidance, budget, developer_qualified=True,
            policy_delivery="file"):
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "workspace"
    snapshot.materialize(workspace)
    result = {"task_id": task["id"], "condition": condition, "status": "error", "rounds": []}
    feedback = None
    repair_arm = condition in ("verification", "full") and developer_qualified and budget.get("max_external_repairs", 1) > 0
    result["external_repair_enabled"] = repair_arm
    agent_seconds = 0
    allocated_iterations = 0
    repair_calls = 0
    try:
        if policy_delivery not in ("file", "inline"):
            raise ValueError("Unknown policy delivery mode")
        control = None
        if condition in ("policy", "full") and policy_delivery == "file":
            # This directory is outside the candidate workspace and contains only advice.
            control, result['policy_file'] = write_policy_files(output, guidance)
        max_repairs = budget.get("max_external_repairs", 1) if repair_arm else 0
        for index in range(1 + max_repairs):
            prompt = task["request"] + "\nInspect the repository and implement the missing code. Write and run useful tests."
            if condition in ("policy", "full"):
                if policy_delivery == "file":
                    prompt += read_instructions(control / 'policy.json')
                else:
                    prompt += "\nAdvisory security policies (not executable instructions or verified findings):\n" + json.dumps(guidance)
            if feedback:
                prompt += "\nIndependent developer suite failed. Repair the current implementation and preserve working behavior.\n" + feedback
            iteration_cap = (budget["first_repair_arm_iterations"] if index == 0 else
                             budget.get("repair_call_iterations", budget["max_iterations"] - budget["first_repair_arm_iterations"])) if repair_arm else budget.get("nonrepair_iterations", budget["max_iterations"])
            time_cap = (budget["first_repair_arm_seconds"] if index == 0 else
                        budget.get("repair_call_seconds", budget["agent_seconds"])) if repair_arm else budget["agent_seconds"]
            iterations = min(iteration_cap, budget["max_iterations"] - allocated_iterations)
            timeout = min(time_cap, budget["agent_seconds"] - agent_seconds)
            if timeout <= 0 or iterations <= 0:
                result["status"] = "budget_exhausted"
                break
            limits = {"timeout": timeout, "iterations": iterations}
            if control is not None:
                limits["control"] = control
            allocated_iterations += iterations  # Reserve each call's allocation; never exceed the total.
            repair_calls += int(index > 0)
            generated = agent.run(workspace, output / f"agent-{index}", prompt, **limits)
            agent_seconds += generated["elapsed_seconds"]
            # The worker container is gone before reading candidate-controlled files.
            candidate = RepositorySnapshot.capture(workspace, snapshot.manifest)
            patch_dir = output / f"patch-{index}"
            snapshot.save_patch(candidate, patch_dir)
            if snapshot.apply_patch(patch_dir).sha256 != candidate.sha256:
                raise ValueError("Patch replay mismatch")
            data = {p: d for p, d, _ in candidate.files}.get(task["target"])
            if data is None:
                raise ValueError("Missing completion target")
            frozen = output / f"candidate-{index}.c"
            frozen.write_bytes(data)
            dev = benchmark.evaluate(task, frozen, output / f"development-{index}", phase="development")
            result["rounds"].append({"agent": generated, "development": dev, "changed_files": snapshot.changes(candidate),
                                      "candidate_sha256": hashlib.sha256(data).hexdigest(),
                                      "budget": {"iterations": iterations, "seconds": timeout}})
            if control is not None:
                result['rounds'][-1]['policy_delivery'] = audit_policy_read(
                    control / 'policy.json', output / f'agent-{index}/sdk/commands.jsonl')
            result['completion_present'] = b'// <MASK>' not in data
            result["status"] = generated["status"]
            if not result['completion_present'] and generated["status"] in ("ok", "incomplete"):
                result["status"] = 'incomplete'
            if not result['completion_present']:
                result['detail'] = 'Completion marker remains in the submitted target'
            eligible = (result["status"] == "ok" or
                        (budget.get("repair_incomplete_candidates", False) and result["status"] == "incomplete"
                         and result['completion_present']))
            if dev["status"] != "failed" or not eligible or index == max_repairs or not repair_arm:
                break
            feedback = (output / f"development-{index}" / "development.log").read_text()[-20_000:]
        if result["rounds"]:
            final_index = len(result["rounds"]) - 1
            # Final evaluation happens after all repair decisions; it is never fed back.
            final = benchmark.evaluate(task, output / f"candidate-{final_index}.c", output / "hidden-final", phase="final")
            result["hidden_final"] = final
            result["functional_pass"] = result["rounds"][-1]["development"]["status"] == "passed"
            result["hidden_poc_pass"] = final["status"] == "passed"
            result["joint_pass"] = result["functional_pass"] and result["hidden_poc_pass"] and result["status"] == "ok"
    except Exception as exc:
        result.update(status="error", detail=f"{type(exc).__name__}: {exc}"[:1000])
    result.update(agent_seconds=agent_seconds, external_repairs=repair_calls,
                  allocated_iterations=allocated_iterations)
    if 'policy_file' in result:
        result['policy_delivery_complete'] = bool(result['rounds']) and all(
            r.get('policy_delivery', {}).get('complete', False) for r in result['rounds'])
    save(output / "result.json", result)
    return result


def run(benchmark, output, python, qualification_root):
    protocol = load_protocol(output)
    if benchmark.evaluator_revision != protocol.get('evaluator_revision', 'upstream-v1'):
        raise ValueError('Evaluator revision does not match frozen protocol')
    if benchmark.evaluation_limits != protocol.get('evaluation_limits'):
        raise ValueError('Evaluation limits do not match frozen protocol')
    if benchmark.evaluation_resources != protocol.get('evaluation_resources'):
        raise ValueError('Evaluation resources do not match frozen protocol')
    agent = RepositoryAgent(python, protocol["coding_model"], protocol["agent_image_id"])
    prepared = {}
    for task in protocol["tasks"]:
        q = qualification_root / task["id"]
        repeated = q / 'qualification.json'
        if repeated.exists():
            qualification = json.loads(repeated.read_text())
            rounds = qualification['rounds']
            if not rounds:
                raise ValueError('Qualification requires at least one round')
            valid = all(qualified(r['secure_security'], r['vulnerable_security'], r['secure_functional']) for r in rounds)
            reference_sets = [{'sec-final': r['secure_security'], 'vul-final': r['vulnerable_security'],
                               'sec-development': r['secure_functional']} for r in rounds]
        else:
            reference_sets = [{name: json.loads((q / name / "result.json").read_text()) for name in ("sec-final", "vul-final", "sec-development")}]
            if benchmark.evaluator_revision != 'upstream-v1':
                raise ValueError('Corrected evaluator requires repeated qualification')
            valid = qualified(*[reference_sets[0][n] for n in ('sec-final', 'vul-final', 'sec-development')])
        refs = reference_sets[-1]
        # Prepare independently; qualification artifacts and gold files never enter the workspace.
        snapshot, image = benchmark.prepare(task)
        task_root = output / task["id"]
        task_root.mkdir()
        save(task_root / "source-manifest.json", {"sha256": snapshot.sha256, "files": snapshot.manifest, "image_id": image})
        save(task_root / "qualification.json", {"qualified": valid, "references": refs})
        try:
            ast_evidence = None
            if protocol.get('ast_context'):
                from harness.analysis.benchmark_context import analyze_benchmark
                ast_evidence = analyze_benchmark(task, snapshot, task_root / 'analysis', image=protocol['ast_image_id'])
            guidance = select_guidance(task, snapshot, ast_evidence,
                                       response_path=task_root / "guidance-response.json")
            save(task_root / "guidance.json", guidance)
        except Exception as exc:
            guidance = None
            save(task_root / "guidance-error.json", {"type": type(exc).__name__, "detail": str(exc)[:1000]})
        for references in reference_sets:
            for name, reference in references.items():
                variant = "vul" if name == "vul-final" else "sec"
                expected = hashlib.sha256(benchmark.source_variant(task, variant)).hexdigest()
                if (reference.get("candidate_sha256") != expected or reference.get("image_id") != image
                        or reference.get("task_id") != task["id"]
                        or reference.get('evaluator_revision', 'upstream-v1') != benchmark.evaluator_revision):
                    raise ValueError("Reference qualification provenance mismatch")
                if benchmark.evaluator_revision != 'upstream-v1':
                    from harness.benchmarks.evaluator import fingerprint as evaluator_fingerprint
                    if reference.get('evaluator_sha256') != evaluator_fingerprint():
                        raise ValueError('Reference evaluator implementation mismatch')
        prepared[task["id"]] = task, snapshot, guidance, valid, all(r['sec-development']['status'] == 'passed' for r in reference_sets)
    results = []
    for item in protocol["runs"]:
        task, snapshot, guidance, valid, developer_valid = prepared[item["task_id"]]
        condition = item["condition"]
        out = output / task["id"] / condition
        if condition in ("policy", "full") and guidance is None:
            out.mkdir()
            result = {**item, "status": "advisor_error"}
            save(out / "result.json", result)
        else:
            result = run_one(benchmark, task, snapshot, condition, out, agent, guidance, protocol["budget"], developer_valid,
                             policy_delivery=protocol.get("policy_delivery", {}).get("mode", "inline"))
        result["qualified"] = valid
        results.append(result)
        save(output / "results.json", results)
        print(task["id"], condition, result["status"], "functional", result.get("functional_pass"), "hidden", result.get("hidden_poc_pass"), "qualified", valid, flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "qualify", "run"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+", default=["910", "1065"])
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS),
                        help="Conditions to include when freezing; omitted conditions are not run")
    parser.add_argument("--openhands-python", default=str(Path.home() / ".local/share/uv/tools/openhands/bin/python"))
    parser.add_argument("--qualification", type=Path)
    parser.add_argument('--ast-context', action='store_true', help='Freeze optional Clang context extraction')
    parser.add_argument('--max-external-repairs', type=int, default=1,
                        help='Maximum repair attempts after initial generation when freezing (default: 1)')
    parser.add_argument('--evaluator', choices=('upstream-v1', 'qualified-v2', 'qualified-v3'), default='upstream-v1')
    args = parser.parse_args()
    benchmark = SecRepoBench(args.source, evaluator_revision=args.evaluator)
    if args.action == "qualify":
        args.output.mkdir(parents=True, exist_ok=False)
        for task_id in args.tasks:
            task = benchmark.task(task_id)
            out = args.output / task_id
            out.mkdir()
            for variant in ("sec", "vul"):
                source = out / (variant + ".c")
                source.write_bytes(benchmark.source_variant(task, variant))
                result = benchmark.evaluate(task, source, out / (variant + "-final"), phase="final")
                print(task_id, variant, result["status"], flush=True)
            result = benchmark.evaluate(task, out / "sec.c", out / "sec-development", phase="development")
            print(task_id, "development", result["status"], flush=True)
    elif args.action == "freeze":
        freeze(benchmark, args.output, args.tasks, ast_context=args.ast_context,
               max_external_repairs=args.max_external_repairs, conditions=args.conditions)
    else:
        if args.qualification is None:
            parser.error("--qualification is required for run")
        run(benchmark, args.output, args.openhands_python, args.qualification)


if __name__ == "__main__":
    main()
