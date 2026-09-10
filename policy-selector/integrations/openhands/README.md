# OpenHands compatibility entrypoint

Verified on the four previous unsuccessful guided cases: four actual MCP calls succeeded, with 14/14 functional and 16/16 security checks passing. See the [retest report](../../OPENHANDS_RETEST.md).

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
/path/to/openhands/python policy-selector/integrations/openhands/compat_entrypoint.py --self-test
```

It checks schema agreement, required flat arguments, rejection of wrapped arguments,
and idempotent application, without an LLM request.

Repeat the previous failing cases using their exact saved prompts:

```bash
.venv/bin/python policy-selector/evaluation/retest_openhands.py \
  --previous .artifacts/security-comparison-20260909 \
  --output .artifacts/openhands-retest-new
```

This creates fresh workspaces/profiles, calls the MCP through OpenHands, and applies
the original external functional/security probes to the generated code. It includes
the three prior no-code runs and the first archive run that had a security failure.
It preserves the original experiment and never manually edits generated code.
