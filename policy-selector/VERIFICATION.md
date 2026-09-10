# Verification — 2026-09-09

**New paired experiment:** [Fixed-integration security comparison](SECURITY_COMPARISON_FIXED.md) records all 12 new generations and distinguishes MCP reliability from code-security findings.

**Latest follow-up:** [OpenHands compatibility fix and failed-case retest](OPENHANDS_RETEST.md): all four previously unsuccessful guided cases passed, with four real MCP calls, 14/14 functional checks and 16/16 security checks.

The independent `policy-selector` MCP is runnable, and OpenHands successfully
called it for a complete coding-and-refinement workflow.

**Follow-up:** This was a smoke test, not evidence of a security improvement.
The [paired security comparison](SECURITY_COMPARISON.md) found no demonstrated gain,
an OpenHands Responses-path MCP schema mismatch, and one vulnerable guided output.
See that report for the broader reliability and security assessment.

## Environment

- Python 3.12.3
- OpenHands CLI 1.13.0, coding model `openai/gpt-5.4-mini`
- Selector requested and returned model: `gpt-5.6-luna`
- MCP SDK 1.30.0; OpenAI SDK 2.54.0
- Catalog: 218 practices, 14 OWASP categories
- Catalog SHA-256: `caa984519b55973b7a96ebaa72b6e1910001281cb6bda327a9651ff7d9dbc6fb`

## Checks

- All 12 offline/protocol tests passed. They cover canonical policy output, unknown IDs, fabricated evidence,
  previous-selection accounting, incomplete responses, bounded correction attempts,
  repository boundaries, credential-file exclusions, symlinks, binary/oversized
  files, named pipes, and real MCP stdio initialization/tool discovery.
- Live stdio calls succeeded for `select_for_task`, `select_for_repository`, and
  `refine_selection`, all using `gpt-5.6-luna`. Deliberately concatenated SQL was
  identified as a gap during refinement.
- OpenHands connected over loopback Streamable HTTP, called `select_for_task`,
  generated `users.py` and `test_users.py`, and called `refine_selection` on the
  exact generated source. The trace confirms actual MCP observation results.
- Generated-code tests passed for normal lookup, absent username, and SQL injection
  without matching or altering database rows; independently rerun successfully.
- OpenHands' saved `selection.json` and `refinement.json` match the MCP responses.

## OpenHands result

| Selected policy | Refinement assessment |
| --- | --- |
| `OWASP-SCP-62aba82e7a6f` — classify data sources by trust | satisfied |
| `OWASP-SCP-b70eb3dca9b7` — validate input and encode output for database operations | uncertain |
| `OWASP-SCP-91517e2a0f4a` — use parameterized queries | satisfied |

The `uncertain` result reflects unspecified username validation requirements;
the test does not establish complete security or policy-selection accuracy.

Provider response IDs observed through OpenHands:

- Selection: `resp_094e750304ad0ca6016aa1930dde8c87d2abe6c22eab00eabc`
- Refinement: `resp_09175736156101a5016aa19344e5ac87d2b1a5902fcddb908f`

OpenHands recovered from tool-argument validation errors during the final run.
Success was checked against actual successful tool observations, generated files,
and test execution, rather than only its CLI exit status.

## Local evidence

- `../.artifacts/mcp-verification/`: live MCP results, including responses extracted
  from the OpenHands trace with the `openhands-` prefix.
- `../.artifacts/openhands-smoke/`: generated helper, tests, and saved policy results.
- `../.artifacts/openhands-smoke-output.log`: complete OpenHands event stream.
- `../.artifacts/openhands-policy/`: OpenHands profile, conversations, and server log.

These runtime artifacts are ignored by Git. See [README](README.md) for commands
to repeat the checks. Live checks use API credits and may select different policies.
