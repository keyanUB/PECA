"""Local OpenHands CLI adapter; its tools run with the current user's privileges."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

from harness.contracts import Candidate


@dataclass(frozen=True)
class AgentResult:
    status: str
    candidate: Candidate | None
    session_id: str | None
    detail: str = ""


class OpenHandsAdapter:
    def __init__(self, model="openai/gpt-5.4-mini", *, allow_local_execution=False):
        if not allow_local_execution:
            raise ValueError("Explicitly enable local OpenHands execution; this adapter is not sandboxed")
        self.model = model

    def run(self, task, workspace, output, prompt, timeout, session_id=None):
        output.mkdir(parents=True, exist_ok=False)
        (output / "prompt.txt").write_text(prompt)
        state = workspace.parent / "agent-state"
        state.mkdir(mode=0o700, exist_ok=True)
        # The harness invokes Policy Advisor itself. The agent gets its saved guidance.
        (state / "mcp.json").write_text('{"mcpServers": {}}\n')
        root = Path(__file__).resolve().parents[2]
        local = root / ".venv-openhands/bin/openhands"
        executable = str(local) if local.is_file() else shutil.which("openhands")
        if not executable or not os.getenv("OPENAI_API_KEY"):
            return AgentResult("error", None, session_id, "OpenHands and OPENAI_API_KEY are required")
        python = Path(executable).resolve().parent / "python"
        entry = root / "policy-advisor-mcp/integrations/openhands/compat_entrypoint.py"
        command = [str(python), str(entry), "--override-with-envs", "--headless", "--json",
                   "-f", str((output / "prompt.txt").resolve())]
        if session_id:
            command += ["--resume", str(uuid.UUID(session_id))]
        env = {**os.environ, "OPENHANDS_PERSISTENCE_DIR": str(state.resolve()),
               "OPENHANDS_CONVERSATIONS_DIR": str((state / "conversations").resolve()),
               "OPENHANDS_WORK_DIR": str(workspace.resolve()),
               "LLM_MODEL": self.model, "LLM_API_KEY": os.environ["OPENAI_API_KEY"]}
        env.pop("LLM_BASE_URL", None)
        started = time.monotonic()
        timed_out = False
        process = None
        try:
            with (output / "trace.log").open("wb") as log:
                process = subprocess.Popen(command, cwd=workspace, env=env, stdout=log, stderr=log,
                                           start_new_session=True)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                finally:
                    # Retire background tools too before snapshotting the candidate.
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=5)
                    except ProcessLookupError:
                        pass
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    finally:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            sessions = list((state / "conversations").glob("*/base_state.json"))
            if session_id is None and len(sessions) == 1:
                session_id = str(uuid.UUID(sessions[0].parent.name))
            candidate = None
            try:
                candidate = Candidate.from_file(task.task_id, workspace / "solution.py")
            except (OSError, ValueError):
                pass
            status = "timeout" if timed_out else "ok" if process.returncode == 0 and candidate else "error"
            result = AgentResult(status, candidate, session_id,
                                 "" if status == "ok" else "Agent timed out, exited unsuccessfully, or produced no valid solution.py")
        except OSError as exc:
            result = AgentResult("error", None, session_id, type(exc).__name__)
        (output / "agent.json").write_text(json.dumps({
            "status": result.status, "detail": result.detail, "session_id": result.session_id,
            "resumed": bool("--resume" in command), "model": self.model,
            "python_executable": str(python),
            "compatibility_sha256": hashlib.sha256(entry.read_bytes()).hexdigest(),
            "elapsed_seconds": time.monotonic() - started,
            "candidate_sha256": result.candidate.sha256 if result.candidate else None,
            "exit_code": process.returncode if process else None}, indent=2) + "\n")
        return result
