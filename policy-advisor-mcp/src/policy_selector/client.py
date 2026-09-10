"""Generic MCP CLI bridge for agents that can invoke commands."""

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

import httpx
from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


async def request(command: str, tool: str | None = None, arguments: dict | None = None,
                  url: str | None = None) -> dict:
    async with AsyncExitStack() as stack:
        if url:
            http = await stack.enter_async_context(httpx.AsyncClient(timeout=300))
            read, write, _ = await stack.enter_async_context(streamable_http_client(url, http_client=http))
        else:
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "policy_selector.server"], env=dict(os.environ))
            read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=300)))
        info = await session.initialize()
        discovered = await session.list_tools()
        if command == "list":
            return {"server": info.serverInfo.model_dump(),
                    "tools": [t.model_dump() for t in discovered.tools]}
        definition = next((t for t in discovered.tools if t.name == tool), None)
        if definition is None:
            raise ValueError(f"Unknown MCP tool: {tool}")
        validate(arguments, definition.inputSchema)
        result = await session.call_tool(tool, arguments)
        if result.isError:
            return {"isError": True, "content": [c.model_dump() for c in result.content]}
        if result.structuredContent is not None:
            return result.structuredContent
        return {"content": [c.model_dump() for c in result.content]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Streamable HTTP MCP endpoint; default starts local stdio server")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("list", help="Discover real MCP tool schemas without an LLM request")
    call = subs.add_parser("call", help="Call a discovered tool using a JSON argument file")
    call.add_argument("tool")
    call.add_argument("--input", required=True, help="JSON file, or - for stdin")
    options = parser.parse_args(argv)
    try:
        arguments = None
        if options.command == "call":
            if options.input == "-":
                raw = sys.stdin.buffer.read(1_000_001)
            else:
                with Path(options.input).open("rb") as stream:
                    raw = stream.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Request file exceeds 1,000,000 bytes")
            arguments = json.loads(raw)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object")
        result = asyncio.run(request(options.command, getattr(options, "tool", None), arguments, options.url))
        print(json.dumps(result, indent=2))
        return 1 if result.get("isError") else 0
    except Exception as exc:
        # Async MCP contexts may group errors; expose the leaf failure concisely.
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
