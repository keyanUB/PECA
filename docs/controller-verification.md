# Controller milestone verification — 2026-09-10

Completed the OpenHands adapter, independent acceptance controller, and bounded
external repair loop for the current single-file Python scope.

## Regression tests

- **38 harness tests passed**, including the existing Docker probes and 21 new
  adapter/controller cases.
- **30 Policy Advisor tests passed**.
- Controlled tests cover secure candidates requiring no agent call; same-session
  continuation; functional regressions after security repairs; unchanged repeated
  failures; repair and time budget exhaustion; advisor/adapter failures; stale
  candidate hashes; stale registry/check versions; incomplete baseline results;
  unknown verification; and verifier cleanup uncertainty.
- Failure-control tests use deterministic fixtures, not claims about observed
  model failure rates. The Docker tests independently exercise secure references,
  known vulnerabilities, isolation properties, and timeout handling.

## Live integration demonstrations

OpenHands was configured with `openai/gpt-5.4-mini`. The two policy-guided runs
received actual MCP responses reporting `gpt-5.6-luna`.

| Demonstration | Initial verification | Final verification | Agent calls | External repairs |
| --- | --- | --- | --- | --- |
| Known Tar file-symlink vulnerability, supplied as a seed | 7/8 | 8/8 | 1 | 1 |
| Fresh SQL helper generation with policy guidance | — | 8/8 | 1 | 0 |
| Secure Tar seed, explicit no-policy condition | 8/8 | 8/8 | 0 | 0 |

The archive repair received the failing probe ID and outside-file overwrite
evidence from PECA. The controller reran all functional and security probes after
the agent's repair, including both directory and file symlink cases. No manual
repair edits were supplied.

A separate adapter integration check resumed the actual SQL conversation
`b6f77250-f73a-4dc8-8b96-e8ccda2bd2ae`, requested rerunning its existing tests, and
confirmed the implementation hash stayed unchanged. Independent Docker verification
again passed 8/8. This checks real conversation continuation; it is not an extra
controller repair round or a new independent generation sample.

Advisor response IDs:

- Tar repair: `resp_02b12f347f07e629016aa2e22b015487d2ba5105c597883bbc`.
- SQL generation: `resp_0f1156e2c48f065d016aa2e29cb63487d2be1cfb5419a2783f`.

Local artifacts are under `.artifacts/controller-verification-20260910/`, with
per-case plans, guidance, prompts, OpenHands traces, feedback, candidate snapshots,
Docker verification reports, and final decisions. `audit.json` cross-checks the
reported hashes, counts, models, and resumed session. Raw artifacts are excluded
from Git. See [the controller guide](controller-design.md) for commands.

## Limits

These are workflow demonstrations, not a comparative security-effectiveness study.
The seeded vulnerability was deliberately selected to validate repair. No hidden
benchmark tests were supplied or evaluated. Current obligation mappings are
operator-authored; automated mapping and repository threat-context extraction
remain future work.

OpenHands runs locally under the user's permissions with explicit opt-in. Docker
isolates candidate verification only; it does not protect the host or harness
evidence from malicious coding-agent actions. Candidate code and probes still
share an interpreter inside Docker. Acceptance is scoped to the configured probes,
not a security certification or an adversarial result-integrity guarantee.

The next milestone is repository-level execution and SecRepoBench integration,
with separate development feedback and hidden final evaluation.
