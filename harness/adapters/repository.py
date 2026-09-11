"""Host supervisor for OpenHands SDK with a Docker-only command tool."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

from harness.sandbox import DEFAULT_IMAGE
from harness.policy_delivery import POLICY_READ_COMMAND


def system_prompt(language="C/C++"):
    if not isinstance(language, str) or not language.strip():
        raise ValueError("Agent task language must be a nonempty string")
    return (f"You are a coding agent completing a {language} repository task. "
            "Use the isolated repository shell. Implement the task, run available tests, and finish. "
            "Restrict repository searches to /workspace; avoid recursive searches of parent directories. "
            "Do not seek benchmark answers or hidden tests. Do not access the network.")


def execute_repository_command(sandbox, command):
    try:
        if getattr(sandbox, 'control', None) is not None and command.strip() == POLICY_READ_COMMAND:
            result = sandbox.execute(command, timeout=60, output_limit=None)
            result['policy_read_full'] = True
            return result
        return sandbox.execute(command, timeout=60)
    except TimeoutError:
        # The old container must be gone before the agent receives another usable tool.
        sandbox.restart()
        return {"exit_code": 124, "truncated": False, "sandbox_restarted": True,
                "output": "Command exceeded time/output limits. The container was restarted; "
                          "files in /workspace and read-only policy files remain available, but /tmp state is lost. "
                          "Use narrower searches within /workspace and smaller output ranges, then continue."}


class RepositoryAgent:
    def __init__(self, python, model="openai/gpt-5.4-mini", image=DEFAULT_IMAGE, *, language="C/C++"):
        system_prompt(language)  # Validate the label without restricting programming languages.
        self.python, self.model, self.image = str(python), model, image
        self.language = language

    def run(self, workspace, output, prompt, *, timeout=240, iterations=20, control=None):
        output.mkdir(parents=True, exist_ok=False)
        name = "peca-agent-" + uuid.uuid4().hex
        request = {"workspace": str(workspace.resolve()), "output": str((output / "sdk").resolve()),
                   "prompt": prompt, "model": self.model, "image": self.image,
                   "container_name": name, "max_iterations": iterations, "language": self.language}
        if control is not None:
            request["control"] = str(Path(control).resolve())
        request_path = output / "request.json"
        request_path.write_text(json.dumps(request, indent=2) + "\n")
        started = time.monotonic()
        result = {"status": "error", "container_name": name}
        process = None
        try:
            with (output / "process.log").open("wb") as log:
                process = subprocess.Popen([self.python, str(Path(__file__).with_name("repository_sdk.py")),
                                            str(request_path.resolve())], stdout=log, stderr=subprocess.STDOUT,
                                           cwd=Path(__file__).resolve().parents[2], start_new_session=True)
                try:
                    code = process.wait(timeout=timeout)
                    result.update(status="ok" if code == 0 else "error", exit_code=code)
                except subprocess.TimeoutExpired:
                    result["status"] = "timeout"
        finally:
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            # Worker normally removes its container. Inspect after cleanup to detect failures.
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
            remaining = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"],
                                       capture_output=True, text=True, timeout=15)
            result["cleanup_confirmed"] = remaining.returncode == 0 and not remaining.stdout.strip()
            if not result["cleanup_confirmed"]:
                result["status"] = "error"
            result["elapsed_seconds"] = time.monotonic() - started
            sdk = output / "sdk/result.json"
            if sdk.exists():
                result["sdk"] = json.loads(sdk.read_text())
            if result["status"] == "ok" and result.get("sdk", {}).get("execution_status") != "finished":
                result["status"] = "incomplete"
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
