"""Retest the previous failing guided runs with a process-local OpenHands adapter fix."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from compare import PECA, digest, events_from


CASES = ["sql_search-r1-scp", "sql_search-r2-scp", "tar_extract-r1-scp", "tar_extract-r2-scp"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = args.previous.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    work_root = Path(tempfile.mkdtemp(prefix="peca-openhands-retest-"))
    plan = {"cases": CASES, "coding_model": "openai/gpt-5.4-mini", "selector_model": "gpt-5.6-luna",
            "previous": str(previous), "workspace_root": str(work_root),
            "compatibility_sha256": digest(PECA / "policy-advisor-mcp/integrations/openhands/compat_entrypoint.py"),
            "evaluator_sha256": digest(Path(__file__).with_name("evaluate.py")),
            "prompt_sha256": {name: digest(previous / name / "prompt.txt") for name in CASES},
            "design": "Exact previous prompts, fresh profiles/workspaces, unchanged evaluator. "
                      "Three previous MCP argument failures and one previous security failure. "
                      "No manual changes to generated code; no retries or refinement feedback.",
            "per_run_timeout_seconds": 300}
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")

    def run(name):
        dest = output / name
        dest.mkdir()
        work = work_root / name
        work.mkdir()
        old = json.loads((previous / name / "result.json").read_text())
        prompt = previous / name / "prompt.txt"
        shutil.copy2(prompt, dest / "prompt.txt")
        env = {**os.environ, "POLICY_SELECTOR_MODEL": "gpt-5.6-luna"}
        env.pop("LLM_BASE_URL", None)
        env.pop("OPENHANDS_CONVERSATIONS_DIR", None)
        env.pop("OPENHANDS_WORK_DIR", None)
        command = [sys.executable, str(PECA / "run_openhands_with_policy.py"), "--workspace", str(work),
                   "--state-dir", str(dest / "state"), "--model", plan["coding_model"],
                   "--", "--headless", "--json", "-f", str(prompt)]
        print(f"START {name}", flush=True)
        start = time.monotonic()
        with (dest / "trace.log").open("w") as trace:
            process = subprocess.Popen(command, env=env, stdout=trace, stderr=trace, start_new_session=True)
            timeout = False
            try:
                code = process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                timeout = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait()
        elapsed = time.monotonic() - start
        shutil.copytree(work, dest / "workspace")
        events = events_from(dest / "trace.log")
        selections = []
        for event in events:
            if event.get("kind") == "ObservationEvent" and event.get("tool_name") == "select_for_task":
                obs = event["observation"]
                if not obs.get("is_error"):
                    for block in obs["content"]:
                        try:
                            result = json.loads(block.get("text", ""))
                        except ValueError:
                            continue
                        if isinstance(result, dict) and "selected" in result:
                            selections.append(result)
        (dest / "selections.json").write_text(json.dumps(selections, indent=2) + "\n")
        candidate = dest / "workspace/solution.py"
        evaluation = {"error": "solution.py missing"}
        if candidate.is_file():
            try:
                completed = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("evaluate.py")),
                                            old["task"], str(candidate)], cwd=work, capture_output=True,
                                           text=True, timeout=30, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
                evaluation = json.loads(completed.stdout)
                (dest / "evaluation-stderr.log").write_text(completed.stderr)
            except (ValueError, subprocess.TimeoutExpired) as exc:
                evaluation = {"error": type(exc).__name__}
        errors = [e.get("error", "") for e in events if e.get("kind") == "AgentErrorEvent"
                  and e.get("tool_name") in {"select_for_task", "select_for_repository", "refine_selection", "policy_catalog"}]
        result = {"case": name, "task": old["task"], "elapsed_seconds": round(elapsed, 2),
                  "exit_code": code, "timeout": timeout, "mcp_calls_succeeded": len(selections),
                  "mcp_argument_errors": errors, "evaluation": evaluation,
                  "adapter_applied": "PECA OpenHands MCP compatibility applied: True" in (dest / "trace.log").read_text(),
                  "solution_sha256": digest(candidate) if candidate.is_file() else None,
                  "prompt_unchanged": digest(dest / "prompt.txt") == plan["prompt_sha256"][name]}
        result["success"] = bool(selections) and not errors and not timeout and "tests" in evaluation and all(
            t["passed"] for t in evaluation["tests"])
        (dest / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"DONE {name}: MCP={len(selections)} errors={len(errors)} "
              f"functional={evaluation.get('functional_passed')}/{evaluation.get('functional_total')} "
              f"security={evaluation.get('security_passed')}/{evaluation.get('security_total')}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, CASES))
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"COMPLETE: {sum(r['success'] for r in results)}/{len(results)} passed; {output}", flush=True)
    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
