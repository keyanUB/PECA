import argparse
from dataclasses import asdict
import json
from pathlib import Path

from harness.contracts import Candidate, ObligationBinding, TaskSpec
from .registry import CHECKS
from .runner import DockerVerifier


def main():
    parser = argparse.ArgumentParser(description="Run PECA's reviewed security probes in Docker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("--task", type=Path, required=True, help="TaskSpec JSON")
    run.add_argument("--candidate", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True, help="New evidence directory")
    run.add_argument("--bindings", type=Path, help="Trusted operator-authored obligation/check mapping JSON")
    run.add_argument("--image", default="python:3.12-slim")
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps([asdict(c) for c in CHECKS], indent=2))
        return 0
    try:
        task = TaskSpec(**json.loads(args.task.read_text()))
        candidate = Candidate.from_file(task.task_id, args.candidate)
        bindings = tuple(ObligationBinding(item["obligation_id"], tuple(item["check_ids"]))
                         for item in json.loads(args.bindings.read_text())) if args.bindings else ()
        report = DockerVerifier(args.image).verify(task, candidate, args.output, bindings)
        print(json.dumps(report.to_dict(), indent=2))
        if any(c.status in ("error", "timeout") for c in report.checks):
            return 2
        return 0 if all(c.status == "passed" for c in report.checks) and all(
            o.status == "passed" for o in report.obligations) else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
