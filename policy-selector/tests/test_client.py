from unittest.mock import AsyncMock
import asyncio
import socket
import subprocess
import sys

import pytest

from policy_selector.client import request
from policy_selector.models import CodeFile
from policy_selector.selector import Selector
from policy_selector.server import build_server


@pytest.mark.asyncio
async def test_generic_client_discovers_flat_schema_and_calls_catalog():
    listed = await request("list")
    task = next(t for t in listed["tools"] if t["name"] == "select_for_task")
    assert "task" in task["inputSchema"]["required"]
    assert "data" not in task["inputSchema"]["properties"]
    result = await request("call", "policy_catalog", {})
    assert result["count"] == 218


@pytest.mark.asyncio
async def test_repository_snapshot_does_not_require_server_path(monkeypatch):
    select = AsyncMock(return_value={"selected": []})
    monkeypatch.setattr(Selector, "select", select)
    tool = build_server()._tool_manager.get_tool("select_for_repository")
    await tool.fn(task="Complete the function", files=[CodeFile(path="app.py", content="pass")])
    assert select.call_args.kwargs["coverage"]["mode"] == "client_snapshot"
    assert select.call_args.args[2][0].content == "pass"


@pytest.mark.asyncio
async def test_repository_snapshot_rejects_ambiguous_inputs():
    tool = build_server()._tool_manager.get_tool("select_for_repository")
    with pytest.raises(ValueError, match="exactly one"):
        await tool.fn(task="task", repository_path=".", files=[])
    with pytest.raises(ValueError, match="exactly one"):
        await tool.fn(task="task")
    with pytest.raises(ValueError, match="file_paths"):
        await tool.fn(task="task", files=[], file_paths=["app.py"])


@pytest.mark.asyncio
async def test_generic_client_uses_streamable_http():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "policy_selector.server",
                                "--transport", "streamable-http", "--port", str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            assert process.poll() is None, "HTTP server exited"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            pytest.fail("HTTP server startup timeout")
        result = await request("call", "policy_catalog", {}, f"http://127.0.0.1:{port}/mcp")
        assert result["count"] == 218
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
