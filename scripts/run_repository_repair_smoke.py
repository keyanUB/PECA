"""Seeded C repair smoke test: one real OpenHands repair, no benchmark scoring."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex

from harness.adapters.repository import RepositoryAgent
from harness.benchmarks.pilot import run_one
from harness.repository import RepositorySnapshot
from harness.sandbox import Sandbox


class SeedThenOpenHands:
    def __init__(self, python):
        self.calls = 0
        self.agent = RepositoryAgent(python)

    def run(self, workspace, output, prompt, **kwargs):
        self.calls += 1
        if self.calls == 1:
            output.mkdir()
            return {"status": "ok", "elapsed_seconds": 0, "seeded": True, "cleanup_confirmed": True}
        return self.agent.run(workspace, output, prompt, **kwargs)


class IndexCheck:
    def __init__(self, workspace):
        self.workspace = workspace

    def evaluate(self, task, candidate, output, *, phase):
        output.mkdir()
        test = ("int allowed_index(int,int); int main(void) { return !(allowed_index(0,1) && "
                "!allowed_index(-1,1) && !allowed_index(1,1) && !allowed_index(0,0)); }")
        command = ("printf '%s' " + shlex.quote(candidate.read_text()) + " > /workspace/solution.c\n"
                   "printf '%s' " + shlex.quote(test) + " > /workspace/test.c\n"
                   "cc -Wall -Werror /workspace/solution.c /workspace/test.c -o /workspace/check && /workspace/check")
        with Sandbox(workspace=self.workspace) as box:
            result = box.execute(command)
        (output / (phase + ".log")).write_text(result["output"] +
            "\nExpected allowed_index(-1,1) == 0; reject negative and out-of-range indices.\n")
        return {"status": "passed" if result["exit_code"] == 0 else "failed",
                "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--openhands-python", default=str(Path.home() / ".local/share/uv/tools/openhands/bin/python"))
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "empty").mkdir()
    snapshot = RepositorySnapshot((("solution.c", b"int allowed_index(int index, int length) { return index < length; }\n", 0o644),))
    task = {"id": "seeded-index-check", "target": "solution.c", "request":
            "Implement int allowed_index(int index, int length) in solution.c. It must return true exactly when "
            "0 <= index < length, including rejecting negative indices and empty arrays. Keep this a small "
            "dependency-free C function. Build and run a small regression test, then finish."}
    result = run_one(IndexCheck(root / "empty"), task, snapshot, "verification", root / "run",
                     SeedThenOpenHands(args.openhands_python), None,
                     {"agent_seconds": 240, "max_iterations": 30,
                      "first_repair_arm_iterations": 10, "first_repair_arm_seconds": 60})
    print(json.dumps({k: v for k, v in result.items() if k != "rounds"}, indent=2))
    if result.get("status") != "ok" or not result.get("joint_pass") or result["external_repairs"] != 1:
        raise SystemExit("Seeded repair smoke did not pass")


if __name__ == "__main__":
    main()
