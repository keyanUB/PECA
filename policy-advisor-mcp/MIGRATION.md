# Rename to policy-advisor

The project directory and Python distribution are now `policy-advisor-mcp`.
The MCP server name and primary executable are `policy-advisor`; the generic
client executable is `policy-advisor-client`.

From PECA, upgrade an existing editable installation in this order:

```bash
.venv/bin/python -m pip uninstall -y policy-selector
.venv/bin/python -m pip install -e './policy-advisor-mcp[dev]'
```

Fresh installations only need the second command after creating their venv.
The distribution is installed from this repository; this rename does not imply
that it has been released on PyPI.

Compatibility retained:

- Python imports and module entrypoints remain `policy_selector`.
- `POLICY_SELECTOR_*` environment variables retain their names and behavior.
- `policy-selector` and `policy-selector-client` remain executable aliases.
- MCP tool names, arguments, outputs, policy IDs, and bundled policy data are unchanged.
- The SWE-agent command remains `policy_selector`.

Update paths containing the old directory to `policy-advisor-mcp`. Regenerate
client config samples with `integrations/render_configs.py` into a new directory.
New configurations use the `policy-advisor` server key. Existing client-local
server keys can remain, but assertions about the MCP-reported server name must
expect `policy-advisor`. Do not configure both names for the same server.

The PECA OpenHands launcher already uses the new directory and server key.
Historical experiment artifacts are not rewritten. Historical reports retain
their measured results; future experiment prompts use the new server name, so
their prompt and implementation hashes will differ from pre-rename runs.

## Verification — 2026-09-10

- Reinstalled the distribution under its new name; `pip check` passed.
- All 19 tests passed, including stdio/HTTP MCP calls, both client command names,
  and parsed Codex/Claude/OpenHands configuration samples.
- Both server command names accept `--help`; all bundled policy data and
  attribution files remain byte-for-byte identical to the pre-rename commit.
- A live OpenHands run through the updated launcher completed selection,
  code generation, and refinement. Both MCP responses reported `gpt-5.6-luna`.
  The generated helper passed three tests: normal lookup, absent user, and SQL injection.
- Selection response: `resp_0147e7464f061e91016aa2c021c3cc87d2830e43a7986384d9`.
- Refinement response: `resp_061bd9b712034a8c016aa2c050176887d288c6990c37d7962d`.

Local evidence is stored under `.artifacts/rename-verification-20260910/` and
excluded from Git. These checks validate the rename in the current environment;
they do not constitute new Codex, Claude Code, or SWE-agent end-to-end tests.
