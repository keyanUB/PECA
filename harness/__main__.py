import argparse
import json
from pathlib import Path

from harness.adapters.openhands import OpenHandsAdapter
from harness.contracts import Candidate, ObligationBinding, TaskSpec
from harness.controller import Controller, MCPAdvisor, RunBudget
from harness.verification.runner import DockerVerifier


def main():
    parser = argparse.ArgumentParser(description="Run PECA's OpenHands verification/repair workflow")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--initial-candidate", type=Path, help="Verify a seed before requesting any repair")
    parser.add_argument("--no-policy", action="store_true", help="Explicit no-guidance control condition")
    parser.add_argument("--allow-local-agent", action="store_true", help="Allow headless OpenHands to execute local tools")
    parser.add_argument("--model", default="openai/gpt-5.4-mini")
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--agent-timeout", type=int, default=180)
    parser.add_argument("--total-timeout", type=int, default=600)
    parser.add_argument("--image", default="python:3.12-slim")
    args = parser.parse_args()
    try:
        task = TaskSpec(**json.loads(args.task.read_text()))
        bindings = tuple(ObligationBinding(b["obligation_id"], tuple(b["check_ids"]))
                         for b in json.loads(args.bindings.read_text())) if args.bindings else ()
        candidate = Candidate.from_file(task.task_id, args.initial_candidate) if args.initial_candidate else None
        controller = Controller(OpenHandsAdapter(args.model, allow_local_execution=args.allow_local_agent),
                                DockerVerifier(args.image), None if args.no_policy else MCPAdvisor(),
                                RunBudget(args.max_repairs, args.agent_timeout, args.total_timeout))
        result = controller.run(task, args.output, bindings, candidate)
        print(json.dumps(result, indent=2))
        return 0 if result["decision"]["decision"] == "accept" else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
