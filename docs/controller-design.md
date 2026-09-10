# OpenHands controller milestone

PECA now runs policy selection, agent generation, independent verification, and
bounded external repair for the three single-file Python task families.

## Run

Use PECA's venv, installed OpenHands, a local Docker daemon with the Python 3.12
image, and an exported `OPENAI_API_KEY`:

```bash
.venv/bin/python -m harness \
  --task harness/examples/sql-task.json \
  --output .artifacts/sql-workflow \
  --allow-local-agent
```

To verify a known candidate before spending an agent call:

```bash
.venv/bin/python -m harness \
  --task harness/examples/tar-task.json \
  --initial-candidate harness/tests/fixtures/tar_parent_only.py \
  --bindings harness/examples/tar-bindings.json \
  --output .artifacts/tar-repair-workflow \
  --allow-local-agent
```

Outputs must be new directories. Exit `0` means accepted within the configured
checks' scope; `1` means incomplete or budget-exhausted; `2` is invalid invocation.

## Agent adapter

The OpenHands adapter starts headless generation or resumes an explicit saved
conversation ID. Each controller run uses its own workspace and profile. The
agent receives the task, selected policy guidance, and later failure evidence;
it retains its native tools, testing, and repair behavior. PECA supplies no MCP
tools to the agent in this workflow: the controller calls Policy Advisor through
the standard MCP client before generation and saves the actual response.

This milestone uses task-only policy selection. Structured repository/threat
context extraction and automatic obligation-to-check planning are not implemented.
Bindings remain trusted operator configuration, not model-authored acceptance rules.
`--no-policy` explicitly selects a no-guidance control condition; an advisor failure
in the normal condition stops the run rather than silently falling back.

**Local execution scope:** `--allow-local-agent` explicitly allows the OpenHands
process and its tools to act as the current user. Prompt instructions to stay in
the workspace are not filesystem isolation. Agent tools can potentially access
host credentials and evidence. Docker isolation applies only to independent
candidate verification, not to the coding agent. Use this adapter only in a
trusted development environment; it is not an adversarial-agent sandbox.

## Acceptance rules

All baseline functional and security checks for the task family must be present
exactly once and pass. Results must match the candidate hash, task, current registry
fingerprint, check versions, and kinds. Required obligation bindings must be
accounted for, and no binding may remain unverified. Cleanup uncertainty prevents
acceptance. This is acceptance against a bounded test suite, not proof of security.

- A demonstrated check failure produces targeted repair feedback.
- Missing/stale evidence, infrastructure errors, verifier timeouts, or unmapped
  obligations produce `incomplete`; the agent is not asked to guess infrastructure fixes.
- An unchanged candidate with the same failures stops as `incomplete` (no progress).
- Agent timeouts and exhausted external repair/total time budgets produce
  `budget_exhausted`, retaining the available candidate.
- The total time budget is checked at stage boundaries and limits agent runtime
  and probe execution. Docker setup/cleanup and cancellation can add bounded
  overhead. This is not a hard process-wide deadline or a dollar/token quota.

Defaults: at most two external repair calls, 180 seconds per agent call, and
600 seconds for the run. Fresh generation has at most one initial call plus two
repairs. A supplied candidate is evaluated before any repair call. Secure seeds
therefore incur zero agent calls, though policy selection runs unless disabled.

Every repair reruns the complete family suite. Feedback includes failed check IDs,
their observed details, the exact candidate hash, and whether a previously passing
check regressed. Evidence text is untrusted data; the harness does not execute it.
Visible development probes supply this feedback. Hidden benchmark tests are not
integrated and must never be used for repair feedback in a held-out evaluation.

## Evidence and limitations

The run saves `plan.json`, optional `guidance.json`, per-turn prompts/traces/metadata,
per-round Docker reports and candidate snapshots, feedback JSON, `result.json`,
the final available candidate, and a unified diff from the initial seed (or empty
file for generation). The exact bytes and hashes are authoritative; the readable
diff decodes source with replacement if needed. Raw artifacts remain excluded
from Git. API credentials are not intentionally persisted in configuration.

The verifier's existing in-process tampering limitation still applies. Full
repository patches, automatic obligation planning, hard cost limits, cross-process
controller restart, additional coding-agent adapters, and benchmark evaluation
remain future work. Session continuation is supported within a controller run;
the adapter can also resume an explicit session for integration checks.

## Tests

```bash
PECA_TEST_DOCKER=1 .venv/bin/python -m pytest harness/tests -q
cd policy-advisor-mcp
../.venv/bin/python -m pytest -q
```

Deterministic adapter/controller fixtures test orchestration independently of
model variability. Docker tests validate the probe execution boundary; separate
live demonstrations validate actual MCP and OpenHands integration.
