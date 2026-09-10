"""Exercise installed commands and rendered client configs after migration."""

import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


@pytest.mark.parametrize("command", ["policy-advisor-client", "policy-selector-client"])
def test_installed_client_aliases_discover_server(command):
    executable = Path(sys.executable).parent / command
    run = subprocess.run([str(executable), "list"], capture_output=True, text=True,
                         check=True, timeout=30)
    result = json.loads(run.stdout)
    assert result["server"]["name"] == "policy-advisor"
    assert {t["name"] for t in result["tools"]} == {
        "policy_catalog", "select_for_task", "select_for_repository", "refine_selection"}


def test_generated_configs_use_new_name_and_existing_module(tmp_path):
    project = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(project / "integrations/render_configs.py"),
                    "--repo-root", str(tmp_path), "--output", str(tmp_path / "configs")],
                   check=True, capture_output=True, text=True)
    codex = tomllib.loads((tmp_path / "configs/codex.toml").read_text())
    claude = json.loads((tmp_path / "configs/claude.mcp.json").read_text())
    openhands = json.loads((tmp_path / "configs/openhands.mcp.json").read_text())
    for config, key in [(codex, "mcp_servers"), (claude, "mcpServers"), (openhands, "mcpServers")]:
        assert set(config[key]) == {"policy-advisor"}
    for config, key in [(codex, "mcp_servers"), (claude, "mcpServers")]:
        server = config[key]["policy-advisor"]
        assert Path(server["command"]).is_file()
        assert server["args"] == ["-m", "policy_selector.server"]
