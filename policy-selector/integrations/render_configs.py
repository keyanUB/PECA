"""Render client-specific configuration samples; never modify client profiles."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path,
        default=Path(__file__).resolve().parents[2] / ".venv/bin/python")
    args = parser.parse_args()
    python = str(args.python.absolute())  # Preserve venv symlinks, which determine its environment.
    repo = str(args.repo_root.resolve())
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    codex = f'''[mcp_servers.policy-selector]
command = {json.dumps(python)}
args = ["-m", "policy_selector.server"]
env_vars = ["OPENAI_API_KEY"]
startup_timeout_sec = 20
tool_timeout_sec = 300

[mcp_servers.policy-selector.env]
POLICY_SELECTOR_REPO_ROOT = {json.dumps(repo)}
POLICY_SELECTOR_MODEL = "gpt-5.6-luna"
'''
    claude = {"mcpServers": {"policy-selector": {
        "type": "stdio", "command": python, "args": ["-m", "policy_selector.server"],
        "env": {"OPENAI_API_KEY": "${OPENAI_API_KEY}", "POLICY_SELECTOR_REPO_ROOT": repo,
                "POLICY_SELECTOR_MODEL": "gpt-5.6-luna"}}}}
    openhands = {"mcpServers": {"policy-selector": {
        "transport": "http", "url": "http://127.0.0.1:8765/mcp"}}}
    for name, content in [("codex.toml", codex), ("claude.mcp.json", json.dumps(claude, indent=2)+"\n"),
                          ("openhands.mcp.json", json.dumps(openhands, indent=2)+"\n")]:
        with (output / name).open("x") as stream:
            stream.write(content)
    print(f"Wrote configuration samples to {output}")


if __name__ == "__main__":
    main()
