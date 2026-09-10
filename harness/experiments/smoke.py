"""Live seeded Python repair and MCP smoke, outside the experimental run matrix."""
import argparse
import json
from pathlib import Path
import time

from harness.adapters.repository import RepositoryAgent
from harness.contracts import TaskSpec
from harness.controller import MCPAdvisor
from harness.verification.runner import DockerVerifier
from .simple import PYTHON, generate, image_id, protocol, save, sources


class SeedThenAgent:
    def __init__(self, agent):
        self.agent, self.calls = agent, 0

    def run(self, workspace, output, prompt, **limits):
        self.calls += 1
        if self.calls == 1:
            output.mkdir()
            return {"status": "ok", "elapsed_seconds": 0, "cleanup_confirmed": True, "seeded": True}
        return self.agent.run(workspace, output, prompt, **limits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--openhands-python", type=Path, default=PYTHON)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    start_sources = sources()
    plan = protocol()
    task = TaskSpec("smoke-sql-repair", "sql_search",
                    "Repair the existing solution.py helper search_users(connection, query). "
                    "The SQLite users table has id and username columns. Return matching (id, username) rows "
                    "ordered by id for a literal case-insensitive substring query. Preserve the connection and rows. "
                    "Use only the standard library and test both ordinary and unusual search text.", "smoke-v1")
    started = time.monotonic()
    guidance = MCPAdvisor().select(task, 150)
    save(root / "guidance.json", {"response": guidance, "elapsed_seconds": time.monotonic() - started})
    agent = SeedThenAgent(RepositoryAgent(args.openhands_python, plan["coding_model"],
                                         image_id(plan["images_observed"]["agent"]), language="Python"))
    result = generate(task, "full", root / "run", agent, DockerVerifier(image_id("python:3.12-slim")),
                      plan["common_instructions"], plan["budget"], guidance,
                      seed=b"def search_users(connection, query):\n    return []\n")
    passed = (sources() == start_sources and result["status"] == "completed" and result["external_repairs"] == 1
              and result["rounds"][-1]["development"]["status"] == "passed")
    save(root / "smoke.json", {"passed": passed, "source_sha256": start_sources, "result": result,
                               "scope": "One seeded development repair and live MCP; no final-suite feedback or effectiveness scoring"})
    print(json.dumps({"passed": passed, "agent_seconds": result["agent_seconds"], "repairs": result["external_repairs"]}))
    if not passed:
        raise SystemExit("Live smoke failed; preserve evidence")


if __name__ == "__main__":
    main()
