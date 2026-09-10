"""Launch OpenHands connected to PECA's independent policy-selector MCP service."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--model", default="openai/gpt-5.4-mini", help="OpenHands coding model")
    parser.add_argument("--state-dir", type=Path, help="Separate OpenHands profile/log directory")
    parser.add_argument("--openhands-python", type=Path, help="Python interpreter with OpenHands installed")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="OpenHands options after --")
    options = parser.parse_args()
    workspace = options.workspace.expanduser().resolve()
    python = ROOT / ".venv/bin/python"
    local_openhands = ROOT / ".venv-openhands/bin/openhands"
    openhands = str(local_openhands) if local_openhands.is_file() else shutil.which("openhands")
    if not workspace.is_dir() or not python.is_file() or not openhands:
        parser.error("Need an existing workspace, PECA .venv with policy-selector installed, and OpenHands")
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("Export OPENAI_API_KEY before launching")
    openhands_python = options.openhands_python or Path(openhands).resolve().parent / "python"
    if not openhands_python.is_file():
        parser.error("Provide --openhands-python for the Python environment with OpenHands installed")
    compatibility = ROOT / "policy-selector/integrations/openhands/compat_entrypoint.py"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    state = (options.state_dir or ROOT / ".artifacts/openhands-policy").expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = {"mcpServers": {"policy-selector": {
        "transport": "http", "url": f"http://127.0.0.1:{port}/mcp"}}}
    # Only the loopback URL is persisted; credentials stay in process environments.
    env = {**os.environ, "POLICY_SELECTOR_REPO_ROOT": str(workspace)}
    with (state / "selector-server.log").open("w") as log:
        server = subprocess.Popen([str(python), "-m", "policy_selector.server",
            "--transport", "streamable-http", "--port", str(port)], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while True:
                if server.poll() is not None:
                    raise RuntimeError(f"MCP startup failed; see {state / 'selector-server.log'}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Timed out waiting for policy-selector")
                    time.sleep(0.1)
            (state / "mcp.json").write_text(json.dumps(config, indent=2) + "\n")
            env.update({"OPENHANDS_PERSISTENCE_DIR": str(state),
                        "LLM_MODEL": options.model, "LLM_API_KEY": os.environ["OPENAI_API_KEY"]})
            forwarded = options.args[1:] if options.args[:1] == ["--"] else options.args
            print(f"policy-selector ready; OpenHands workspace: {workspace}", flush=True)
            return subprocess.call([str(openhands_python), str(compatibility),
                                    "--override-with-envs", *forwarded], cwd=workspace, env=env)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
