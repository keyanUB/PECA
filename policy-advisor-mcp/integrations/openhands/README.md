# OpenHands compatibility entrypoint

`compat_entrypoint.py` repairs the installed OpenHands 1.13.0 MCP-to-Responses
schema mismatch in the running Python process. It builds the Responses function
schema from the same MCP input schema used by the Chat Completions conversion and
execution validator. It preserves security-risk/summary fields and does not accept
invalid wrapped `data` arguments.

The fix is applied only when `MCPToolDefinition.to_responses_tool` is still the
inherited generic `ToolDefinition` implementation. A native override is left in
place; repeated application is a no-op. Compatibility with other OpenHands releases
must be verified with their own interpreter and integration tests.

PECA's `run_openhands_with_policy.py` uses this entrypoint automatically:

```bash
python3 run_openhands_with_policy.py --workspace /path/to/project
```

It normally locates Python beside the installed OpenHands console script. For
nonstandard installations, provide `--openhands-python /path/to/openhands/python`.
A standalone native binary cannot load this Python compatibility entrypoint.
Use `--state-dir /path/to/profile` for an isolated OpenHands profile.

The installed OpenHands package is not edited. Running the bare `openhands` command
does not load this fix. No OpenHands-specific parameters are added to the independent
MCP service, and other MCP clients do not load this entrypoint.

Run the schema regression check with the Python interpreter containing OpenHands:

```bash
/path/to/openhands/python policy-advisor-mcp/integrations/openhands/compat_entrypoint.py --self-test
```

It checks schema agreement, required flat arguments, rejection of wrapped arguments,
and idempotent application, without an LLM request.

To generate fresh live integration evidence, run the current harness smoke:

```bash
.venv/bin/python -m harness.experiments.smoke \
  --output .artifacts/simple-smoke
```

This checks controller-to-MCP integration and a seeded repair through the isolated
OpenHands SDK adapter. It does not exercise stock CLI MCP tool calling. The schema
self-test above specifically checks this compatibility entrypoint. Historical
retest artifacts have been removed.
