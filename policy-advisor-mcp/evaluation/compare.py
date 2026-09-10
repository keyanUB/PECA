"""Run a fixed paired OpenHands experiment; no selector or generator tuning."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from cases import COMMON, TASKS, TREATMENT


PECA = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events_from(path):
    events = []
    for piece in path.read_text(errors="replace").split("--JSON Event--")[1:]:
        try:
            event, _ = json.JSONDecoder().raw_decode(piece.lstrip())
            events.append(event)
        except ValueError:
            continue
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace_root = Path(tempfile.mkdtemp(prefix="peca-comparison-"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    python = PECA / ".venv/bin/python"
    openhands = shutil.which("openhands")
    if not openhands or not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OpenHands and OPENAI_API_KEY are required")
    openhands_python = Path(openhands).resolve().parent / "python"
    compatibility = PECA / "policy-advisor-mcp/integrations/openhands/compat_entrypoint.py"
    if not openhands_python.is_file():
        raise RuntimeError("Cannot locate OpenHands Python interpreter")
    plan = {"tasks": TASKS, "common_instructions": COMMON, "treatment": TREATMENT,
            "repetitions": args.repetitions, "coding_model": "openai/gpt-5.4-mini",
            "selector_model": "gpt-5.6-luna", "per_run_timeout_seconds": 300,
            "parallel_runs": 2, "workspace_root": str(workspace_root),
            "compatibility_sha256": digest(compatibility),
            "runner_sha256": digest(Path(__file__)),
            "cases_sha256": digest(Path(__file__).with_name("cases.py")),
            "openhands_python": str(openhands_python),
            "evaluator_sha256": digest(Path(__file__).with_name("evaluate.py")),
            "selector_sha256": digest(PECA / "policy-advisor-mcp/src/policy_selector/selector.py"),
            "catalog_sha256": digest(PECA / "policy-advisor-mcp/src/policy_selector/data/owasp-scp.json"),
            "design": "Two fresh profiles/workspaces per task and repetition. Baseline has no MCP. "
                      "Treatment calls task selection before coding. No refinement feedback. "
                      "Identical model, task, common prompt and timeout. Both arms use the same compatibility entrypoint. "
                      "External tests fixed before generation."}
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    env = {**os.environ, "POLICY_SELECTOR_REPO_ROOT": str(workspace_root),
           "POLICY_SELECTOR_MODEL": "gpt-5.6-luna"}
    with (output / "mcp-server.log").open("w") as server_log:
        server = subprocess.Popen([str(python), "-m", "policy_selector.server", "--transport",
                                   "streamable-http", "--port", str(port)], env=env,
                                  stdout=server_log, stderr=server_log)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("MCP server exited at startup")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("MCP server startup timeout")

            def run(task, repetition, arm):
                name = f"{task}-r{repetition}-{arm}"
                target = output / name
                target.mkdir()
                work = workspace_root / name
                work.mkdir()
                state = target / "openhands-state"
                state.mkdir(mode=0o700)
                mcp = {"mcpServers": {}}
                if arm == "scp":
                    mcp["mcpServers"]["policy-advisor"] = {"transport": "http", "url": f"http://127.0.0.1:{port}/mcp"}
                (state / "mcp.json").write_text(json.dumps(mcp))
                prompt = TASKS[task] + "\n\n" + COMMON
                if arm == "scp":
                    prompt += "\n\n" + TREATMENT
                (target / "prompt.txt").write_text(prompt)
                run_env = {**os.environ, "OPENHANDS_PERSISTENCE_DIR": str(state),
                           "OPENHANDS_WORK_DIR": str(work), "OPENHANDS_CONVERSATIONS_DIR": str(state / "conversations"),
                           "LLM_MODEL": plan["coding_model"], "LLM_API_KEY": os.environ["OPENAI_API_KEY"]}
                # Prevent an unrelated provider base URL from changing the paired coding endpoint.
                run_env.pop("LLM_BASE_URL", None)
                start = time.monotonic()
                print(f"START {name}", flush=True)
                with (target / "trace.log").open("w") as trace:
                    process = subprocess.Popen([str(openhands_python), str(compatibility), "--override-with-envs", "--headless", "--json",
                                                "-f", str(target / "prompt.txt")], cwd=work, env=run_env,
                                               stdout=trace, stderr=trace, start_new_session=True)
                    timed_out = False
                    try:
                        exit_code = process.wait(timeout=300)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            exit_code = process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            exit_code = process.wait()
                elapsed = time.monotonic() - start
                shutil.copytree(work, target / "workspace")
                events = events_from(target / "trace.log")
                selections = []
                tool_calls = []
                for event in events:
                    if event.get("kind") == "ActionEvent":
                        tool_calls.append(event.get("tool_name"))
                    if event.get("kind") == "ObservationEvent" and event.get("tool_name") == "select_for_task":
                        observation = event["observation"]
                        if not observation.get("is_error"):
                            for content in observation.get("content", []):
                                try:
                                    selection = json.loads(content.get("text", ""))
                                except ValueError:
                                    continue
                                if isinstance(selection, dict) and "selected" in selection:
                                    selections.append(selection)
                (target / "selections.json").write_text(json.dumps(selections, indent=2) + "\n")
                compliance = bool(selections) if arm == "scp" else not selections
                evaluation = {"error": "solution.py missing"}
                candidate = target / "workspace/solution.py"
                if candidate.is_file():
                    try:
                        checked = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("evaluate.py")),
                                                  task, str(candidate)], capture_output=True, text=True,
                                                 timeout=30, cwd=work,
                                                 env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
                        evaluation = json.loads(checked.stdout)
                        (target / "evaluation-stderr.log").write_text(checked.stderr)
                    except (ValueError, subprocess.TimeoutExpired) as exc:
                        evaluation = {"error": type(exc).__name__}
                result = {"task": task, "repetition": repetition, "arm": arm, "exit_code": exit_code,
                          "adapter_applied": "PECA OpenHands MCP compatibility applied: True" in (target / "trace.log").read_text(errors="replace"),
                          "prompt_sha256": digest(target / "prompt.txt"),
                          "timed_out": timed_out, "elapsed_seconds": round(elapsed, 2),
                          "treatment_compliant": compliance, "mcp_selection_count": len(selections),
                          "tool_calls": tool_calls, "evaluation": evaluation,
                          "solution_sha256": digest(candidate) if candidate.is_file() else None}
                (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                print(f"DONE {name}: compliance={compliance}, functional="
                      f"{evaluation.get('functional_passed')}/{evaluation.get('functional_total')}, security="
                      f"{evaluation.get('security_passed')}/{evaluation.get('security_total')}", flush=True)
                return result

            results = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                for repetition in range(1, args.repetitions + 1):
                    for task in TASKS:
                        order = ["baseline", "scp"] if repetition % 2 else ["scp", "baseline"]
                        futures = [pool.submit(run, task, repetition, arm) for arm in order]
                        results.extend(f.result() for f in futures)
                        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(f"COMPLETE {output}", flush=True)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
