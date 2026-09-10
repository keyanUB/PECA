# policy-advisor

An independent Python MCP server that uses **gpt-5.6-luna** to select OWASP Secure
Coding Practices for coding tasks, incomplete repositories, and generated code.
OpenHands is one client; the server has no dependency on OpenHands.

See [cross-agent integrations](integrations/README.md) for Codex, Claude Code,
SWE-agent, the generic MCP CLI bridge, and the distinction between configuration
support and verified end-to-end client support.

## Install

From the PECA directory, using Python 3.12+:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './policy-advisor-mcp[dev]'
```

`OPENAI_API_KEY` must be present in the server's environment for selection calls.
The server does not read a `.env` file automatically. Keys are not part of tool
arguments or MCP configuration files. Catalog discovery works without a key.

## Run independently

```bash
# stdio: an MCP client starts this process and communicates over stdin/stdout
.venv/bin/policy-advisor

# HTTP: a local MCP client connects to http://127.0.0.1:8765/mcp
POLICY_SELECTOR_REPO_ROOT="$PWD" .venv/bin/policy-advisor --transport streamable-http
```

Stdio mode waiting silently is normal: it expects MCP JSON-RPC, not conversational
terminal input. The HTTP service binds only to loopback. It is intended for a
trusted local client, and does not implement multi-user authentication.

## Tools

All selection/refinement tools optionally accept `security_context` and
`propose_obligations` (default `false`). With neither supplied, existing behavior
and response fields are preserved. Context or `propose_obligations=true` adds
proposed obligations, always marked advisory and unverified. No checks are executed.
See the [contract](../docs/harness-design.md) and
[example request](examples/security-context.json).

```bash
.venv/bin/policy-advisor-client call select_for_task \
  --input policy-advisor-mcp/examples/security-context.json
```

| Tool | Input | Output |
| --- | --- | --- |
| `policy_catalog` | None | Source provenance, catalog hash, categories, all SCPs; no LLM call |
| `select_for_task` | `task` | Applicable SCPs for the coding request |
| `select_for_repository` | `task`, either `repository_path` (optional `file_paths`) or a `files` snapshot | Selection informed by source files, plus coverage and omissions |
| `refine_selection` | `task`, `generated_code`, `previous_selection` | Retained/added policies, explained removals, and implementation assessment |

Task example:

```json
{"task": "Implement a Python SQLite lookup using an untrusted username."}
```

Repository example, with the server's repository root set to the parent directory:

```json
{
  "task": "Complete find_user using a safe SQLite query.",
  "repository_path": "my-project",
  "file_paths": ["users.py", "README.md"]
}
```

Refinement example (use IDs returned by selection):

```json
{
  "task": "Implement a Python SQLite lookup using an untrusted username.",
  "generated_code": [{
    "path": "users.py",
    "content": "def find_user(conn, username):\n    return conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()\n"
  }],
  "previous_selection": [{
    "policy_id": "OWASP-SCP-91517e2a0f4a",
    "rationale": "Untrusted input reaches a SQL query.",
    "guidance": "Bind the username as a query parameter."
  }]
}
```

Results include canonical policy text and source URL, rationale, scoped guidance,
exact task/file evidence, catalog SHA-256, requested/returned model names, provider
response ID, and usage. `attempts` records every API response and its usage,
including a correction attempt; top-level `usage` is the final response's usage.

Refinement marks selected items `retained` or `added`, and lists `removed` items
separately. Assessment can be `satisfied`, `gap`, or `uncertain`; initial selection
uses `applicable` or `uncertain`. Satisfying a control does not remove its applicability.
Every previous policy must be accounted for. Unknown IDs and fabricated evidence
are rejected, with at most one LLM correction attempt. API errors have no automatic
retry or model fallback.

## Use with OpenHands

From PECA, with OpenHands installed and `OPENAI_API_KEY` exported:

```bash
python3 run_openhands_with_policy.py --workspace /absolute/path/to/project
```

This starts the independent server on an available loopback port, configures a
PECA-local OpenHands profile, and shuts down the server when OpenHands exits.
The launcher also applies a process-local [OpenHands MCP schema compatibility fix](integrations/openhands/README.md)
for the inherited Responses conversion. The standalone MCP service is unchanged.
It uses `openai/gpt-5.4-mini` for OpenHands and `gpt-5.6-luna` inside the selector.
Use `--model` to change OpenHands' coding model. OpenHands settings and conversation
artifacts live under `PECA/.artifacts/openhands-policy`; your usual OpenHands profile
is not edited. Use a different `--state-dir` for each concurrent launcher instance.

Ask OpenHands to call `select_for_task` before coding and `refine_selection` after
generation. Tool availability alone does not force OpenHands to call a tool.

Repeat the end-to-end smoke test:

```bash
mkdir -p .artifacts/openhands-smoke
python3 run_openhands_with_policy.py --workspace .artifacts/openhands-smoke -- \
  --headless --json -f "$PWD/policy-advisor-mcp/examples/openhands-smoke-task.txt"
```

The task asks OpenHands to call the actual MCP tools, generate a SQLite helper,
test normal/missing/injection inputs, and save `selection.json` and `refinement.json`.
Headless OpenHands executes its chosen actions without interactive confirmation.

For another MCP client, use the stdio command with an absolute executable path and
explicitly forward `OPENAI_API_KEY` from that client's environment. Some MCP clients
do not inherit arbitrary environment variables. Alternatively connect to the local
HTTP server that you launch from your configured shell.

## Configuration and scope

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Required for selection | Selector API credential |
| `POLICY_SELECTOR_MODEL` | `gpt-5.6-luna` | Selector model; never silently substituted |
| `OPENAI_BASE_URL` | OpenAI API | Optional compatible API endpoint |
| `POLICY_SELECTOR_REPO_ROOT` | Server working directory | Boundary for repository reads |
| `POLICY_SELECTOR_EXTRA_CATALOG` | Unset | Additional JSON catalog merged with OWASP |

Repository reads are limited to 40 files and 200,000 UTF-8 bytes. Automatic discovery
checks at most 10,000 file entries, excludes hidden paths, dependency/build directories,
common credential files, binaries, and symlinks. Explicit `file_paths` are recommended
for larger projects. Returned coverage documents skipped files and limits; the tool
does not claim a complete audit of omitted code. It does not execute repository code.
Tasks and selected source contents are sent to the selector API. File-name exclusions
are not a guarantee that source code contains no embedded secrets.

Clients without a shared filesystem can supply `files: [{"path": "src/app.py",
"content": "..."}]` instead of `repository_path`. Snapshots have the same size limits
and explicitly report partial coverage; their path labels are not opened by the server.

Refinement accepts up to 40 named code files totaling 200,000 bytes. Calls are
stateless: pass the previous selection explicitly. No vector database, embeddings,
or keyword prefilter is used; the model receives the entire 218-practice catalog.
The service recommends policies; it does not enforce them or modify code.

## Policy source and extension

The bundled snapshot contains **218 practices across all 14 categories** from the
[official OWASP stable-en checklist](https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/stable-en/02-checklist/05-checklist).
Original text is preserved apart from joined continuation lines and normalized
escaped quotes. IDs are PECA content hashes, not official OWASP identifiers.
See [source attribution](src/policy_selector/data/NOTICE.md).

The historical checklist includes dated advice. The selector is prompted to flag
conflicts; it cannot certify that every policy is suitable for current requirements.

To extend, provide a JSON document with `source` metadata and a `policies` array
matching `src/policy_selector/data/owasp-scp.json`. Each policy requires a unique
`id`, `category`, `text`, and `source_url`. Set `POLICY_SELECTOR_EXTRA_CATALOG` and
restart the server. Duplicate IDs are rejected.

To regenerate the OWASP snapshot after reviewing an upstream update:

```bash
python3 policy-advisor-mcp/scripts/import_owasp.py /path/to/official-checklist.md
```

Unchanged category/text pairs retain their IDs; edited practices receive new IDs.
Review the resulting diff before replacing a snapshot used in experiments.

## Verification

See the [current harness experiment](../harness/README.md#isolated-python-comparison)
for qualification and generation-comparison instructions. Historical experiment
reports and raw results were removed during repository cleanup. A successful smoke
test alone does not demonstrate improved security.

```bash
cd policy-advisor-mcp
../.venv/bin/python -m pytest -q
cd ..
.venv/bin/python policy-advisor-mcp/scripts/verify_mcp.py
```

The first command runs offline tests, including real stdio MCP discovery. The second
makes live selector calls for all three workflows and saves results under
`.artifacts/mcp-verification`. It checks that unsafe SQL is reported as a gap.

Implementation references:
[MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
