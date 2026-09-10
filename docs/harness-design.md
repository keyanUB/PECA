# PECA security context and obligation contract

Policy Advisor accepts optional security context and proposes verification
obligations. Steps 1–3 now also provide [typed harness contracts and a trusted
Docker verifier](../harness/README.md) for three single-file Python task families.
A harness controller, agent adapter, and acceptance engine are not implemented yet.

## Responsibilities

PECA's future context builder identifies assets, untrusted inputs, sensitive
operations, application trust boundaries, and assumptions. Policy Advisor consumes
that context as untrusted evidence and proposes obligations. A separate verifier
must map proposals to reviewed checks; a controller owns acceptance and repair budgets.
The MCP does not enforce process isolation, run suggested checks, or accept patches.

## Context contract

All three selection tools accept `security_context` and `propose_obligations`.
Omitting both preserves the legacy selection response. Supplying any context or
setting `propose_obligations=true` requests additional advisory output.

Context contains five optional claim lists: `assets`, `untrusted_inputs`,
`sensitive_operations`, `trust_boundaries`, and `assumptions`. Each claim has a
unique ID, statement, status (`supported`, `assumed`, or `unknown`), and optional
evidence. Supported claims require a quote from the supplied task or code.
All supplied evidence is checked, regardless of status. Matching a quote validates
provenance only, not the semantic truth of a claim. IDs are unique across all lists.
Context is limited to 20,000 serialized UTF-8 bytes and 20 claims per list.

Evidence sources are `task` or an exact supplied code-file label. Repository
evidence must reference a file actually included in the bounded context. Missing
evidence is an input error; do not fabricate evidence for files that were not read.

## Obligation contract

Each proposal includes an ID, observable requirement, selected policy IDs,
context IDs, applicability conditions, source evidence, suggested check methods
and expected evidence, and limitations. Context IDs must exist, and policy IDs
must be part of this response's selection. Duplicate obligation IDs and fabricated
quotes are rejected. Invalid model proposals use the existing one-correction limit.

The server adds `advisory=true` and `verification_status=unverified` to every
proposal. Suggested checks are descriptive text, never instructions to execute
arbitrary commands. A consumer must not convert these descriptions directly into
privileged execution. The caller's context, including its uncertainty labels, is
echoed without allowing the model to overwrite it.

Refinement can propose obligations against the current code but does not persist
or reconcile earlier obligation IDs. IDs are response-scoped. Policy assessments
such as `satisfied` remain LLM judgments, not execution evidence. Historical
obligation tracking belongs in a later harness contract.

## Next implementation boundary

TaskSpec, immutable Candidate snapshots, CheckResult, and AcceptanceDecision
contracts are defined in `harness/contracts.py`. The verifier binds evidence to
candidate hashes, check versions, and execution environments, and always runs
the family baseline. Read-only container mounts protect probe files. Failed
checks, infrastructure errors, timeouts, and unverified mappings are distinct.
The current verifier does not resist malicious in-process result forgery; see
its documented threat-model limitation. Final benchmark tests must not supply
repair feedback. The next increment is the agent adapter and bounded controller.

Acceptance rules, mandatory checks, and repair budgets must be fixed by PECA's
experiment configuration, not decided by the advisor. Held-out benchmark evaluation
remains separate from the harness's own acceptance decision.

## Initial verification — 2026-09-10

The 30-test suite covers legacy responses, installed CLI aliases, real stdio/HTTP
MCP calls, context bounds and provenance, obligation references, and bounded
model-output correction. A live stdio request using
`policy-advisor-mcp/examples/security-context.json` returned six SCPs and three
advisory obligations from `gpt-5.6-luna` in one attempt. The caller's unknown
symlink assumption remained unknown; every obligation remained unverified.

Response ID: `resp_05a155cf05f47ac3016aa2d8f9c2c487d29cd7540fd262a92d`.
Local response: `.artifacts/context-obligations-verification/response.json`.
This verifies protocol and schema operation, not completeness of threat analysis
or a measured improvement in secure generation. No new benchmark experiment or
agent-level end-to-end run was performed for this extension.
