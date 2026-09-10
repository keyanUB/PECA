import os
import sys
from datetime import timedelta

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_real_stdio_discovery_and_validation(tmp_path):
    env = {**os.environ, "POLICY_SELECTOR_REPO_ROOT": str(tmp_path)}
    env.pop("OPENAI_API_KEY", None)
    server = StdioServerParameters(command=sys.executable,
        args=["-m", "policy_selector.server"], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "policy-selector"
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {
                "policy_catalog", "select_for_task", "select_for_repository", "refine_selection"}
            result = await session.call_tool("policy_catalog", {})
            assert not result.isError
            assert result.structuredContent["count"] == 218
            result = await session.call_tool("select_for_task", {"task": ""})
            assert result.isError
            result = await session.call_tool("select_for_repository", {
                "task": "complete the code", "repository_path": "/"})
            assert result.isError
