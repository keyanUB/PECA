"""Post-hoc diagnostic audit; never feeds results back into the generation comparison."""

import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cases import TASKS


async def main():
    root = Path(sys.argv[1]).resolve()
    selections = json.loads((root / "tar_extract-r1-scp/selections.json").read_text())[-1]
    previous = [{k: p[k] for k in ("policy_id", "rationale", "guidance")}
                for p in selections["selected"]]
    cases = []
    for arm in ("baseline", "scp"):
        code = (root / f"tar_extract-r1-{arm}/workspace/solution.py").read_text()
        cases.append((f"tar-r1-{arm}", TASKS["tar_extract"], code, previous))
    # Known controls exercise selection removal as well as gap/satisfied classification.
    sql_task = "Implement find_user(connection, username) to look up a SQLite user by an untrusted username."
    sql_previous = [
        {"policy_id": "OWASP-SCP-91517e2a0f4a", "rationale": "The task queries a database.", "guidance": "Use bound parameters."},
        {"policy_id": "OWASP-SCP-b183800b3872", "rationale": "The task concerns users.", "guidance": "Hash stored passwords."},
    ]
    cases.append(("sql-secure-control", sql_task,
        "def find_user(connection, username):\n    return connection.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()\n",
        sql_previous))
    cases.append(("sql-vulnerable-control", sql_task,
        "def find_user(connection, username):\n    return connection.execute(\"SELECT * FROM users WHERE username = '\" + username + \"'\").fetchone()\n",
        sql_previous))
    params = StdioServerParameters(command=sys.executable, args=["-m", "policy_selector.server"], env=dict(os.environ))
    output = root / "posthoc-refinement"
    output.mkdir(exist_ok=True)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=280)) as session:
            await session.initialize()
            for name, task, code, prior in cases:
                request = {"task": task, "generated_code": [{"path": "solution.py", "content": code}],
                           "previous_selection": prior}
                (output / f"{name}-request.json").write_text(json.dumps(request, indent=2) + "\n")
                response = await session.call_tool("refine_selection", request)
                if response.isError:
                    value = {"error": [c.model_dump() for c in response.content]}
                else:
                    value = response.structuredContent
                (output / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
                print(name, "error" if response.isError else
                      [(p["policy_id"], p["assessment"]) for p in value["selected"]], flush=True)


if __name__ == "__main__":
    asyncio.run(main())
