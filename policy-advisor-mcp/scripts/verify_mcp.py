"""Exercise all three workflows over real MCP stdio; makes three selector API calls."""

import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


TASK = "Implement a Python SQLite helper find_user(connection, username) that safely looks up a user by untrusted username and returns the matching row."


async def main():
    output = Path(__file__).resolve().parents[2] / ".artifacts/mcp-verification"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="peca-repo-") as directory:
        Path(directory, "users.py").write_text(
            "import sqlite3\n\ndef find_user(connection, username):\n    # TODO: query users safely\n    pass\n")
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "policy_selector.server"],
            env={**os.environ, "POLICY_SELECTOR_REPO_ROOT": directory})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
                info = await session.initialize()
                assert info.serverInfo.name == "policy-advisor"

                async def call(name, arguments):
                    result = await session.call_tool(name, arguments)
                    if result.isError:
                        raise RuntimeError(f"{name}: {result.content}")
                    value = result.structuredContent
                    assert value and value["selected"], f"Empty selection in {name}"
                    (output / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
                    print(f"PASS {name}: {len(value['selected'])} policies; model={value['response_model']}", flush=True)
                    return value

                initial = await call("select_for_task", {"task": TASK})
                await call("select_for_repository", {
                    "task": TASK, "repository_path": directory, "file_paths": ["users.py"]})
                refined = await call("refine_selection", {
                    "task": TASK,
                    "generated_code": [{"path": "users.py", "content":
                        "def find_user(connection, username):\n"
                        "    return connection.execute(\"SELECT * FROM users WHERE username = '\" + username + \"'\").fetchone()\n"}],
                    "previous_selection": [{k: p[k] for k in ("policy_id", "rationale", "guidance")}
                                           for p in initial["selected"]]})
                assert any(p["assessment"] == "gap" for p in refined["selected"]), "Expected SQL injection gap"
                print(f"Artifacts: {output}")


if __name__ == "__main__":
    asyncio.run(main())
