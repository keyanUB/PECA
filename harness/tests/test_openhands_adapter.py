import json
from pathlib import Path
import sys

import pytest

from harness.adapters.openhands import OpenHandsAdapter
from harness.contracts import TaskSpec


TASK = TaskSpec("task", "sql_search", "Implement search_users", "fixture")


def fake_install(tmp_path, monkeypatch, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "openhands"
    executable.touch()
    python = bin_dir / "python"
    python.write_text(f"#!{sys.executable}\n" + body)
    python.chmod(0o755)
    monkeypatch.setattr("harness.adapters.openhands.shutil.which", lambda _: str(executable))
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-test-key")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_starts_and_resumes_explicit_session(tmp_path, monkeypatch):
    workspace = fake_install(tmp_path, monkeypatch, '''import os, sys, json
from pathlib import Path
session = '12345678-1234-5678-1234-567812345678'
state = Path(os.environ['OPENHANDS_CONVERSATIONS_DIR']) / session
state.mkdir(parents=True, exist_ok=True)
(state / 'base_state.json').write_text('{}')
Path('solution.py').write_text('def search_users(c, q): return []')
Path('arguments.json').write_text(json.dumps(sys.argv))
''')
    adapter = OpenHandsAdapter(allow_local_execution=True)
    first = adapter.run(TASK, workspace, tmp_path / "first", "Generate", 5)
    assert first.status == "ok" and first.session_id
    second = adapter.run(TASK, workspace, tmp_path / "second", "Repair", 5, first.session_id)
    assert second.status == "ok" and second.session_id == first.session_id
    arguments = json.loads((workspace / "arguments.json").read_text())
    assert arguments[-2:] == ["--resume", first.session_id]
    assert json.loads((tmp_path / "agent-state/mcp.json").read_text()) == {"mcpServers": {}}
    assert json.loads((tmp_path / "second/agent.json").read_text())["resumed"] is True


@pytest.mark.parametrize("body,expected", [
    ("import sys; sys.exit(3)", "error"),
    ("import time; time.sleep(30)", "timeout"),
    ("pass", "error"),
])
def test_agent_failure_cannot_be_success(tmp_path, monkeypatch, body, expected):
    workspace = fake_install(tmp_path, monkeypatch, body)
    result = OpenHandsAdapter(allow_local_execution=True).run(TASK, workspace, tmp_path / "turn", "task", 0.2)
    assert result.status == expected
    assert result.candidate is None
