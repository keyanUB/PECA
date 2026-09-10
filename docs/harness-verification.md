# Harness steps 1–3 verification — 2026-09-10

## Completed

1. Committed the previously tested MCP security-context and obligation extension
   as `7a58f52`.
2. Added TaskSpec, immutable Candidate snapshots, CheckResult, ObligationBinding,
   ObligationResult, VerificationReport, and the controller-owned AcceptanceDecision
   contract. No acceptance/controller implementation is included.
3. Added a trusted, versioned registry and Docker execution of 22 probes across
   SQL queries, document reads, and archive extraction. Explicit operator bindings
   map obligations to checks; free-form advisor text is never executed.

## Validation

- **17 harness tests passed**, including 11 Docker cases covering all three secure
  references and vulnerable controls, a parent-only symlink defense, timeouts,
  read-only mounts, secret environment exclusion, network isolation, invalid
  Python, and missing output. Six other tests cover snapshot immutability, input
  limits, mapping validation, unverified obligations, backend failure, task identity,
  and evidence-directory overwrite prevention.
- **30 Policy Advisor tests passed** after adding the harness.
- The actual verifier CLI returned exit `0` for the secure Tar reference with
  8/8 checks passed and its mapped obligation passed.
- The CLI returned exit `1` for the parent-only Tar fixture with 7/8 checks passed.
  `tar_extract.preexisting_symlink` passed while
  `tar_extract.preexisting_leaf_symlink` failed: an outside file was overwritten.
  The mapped containment obligation was reported failed.
- Local evidence: `.artifacts/harness-verification-20260910/secure/` and
  `.artifacts/harness-verification-20260910/leaf-gap/`, each containing the exact
  candidate, execution output, and report. These files are excluded from Git.
- Docker image ID used:
  `sha256:ec7d6c95cd3692a2e2d228a8b1ca74e4025b54121fcc4c5da6f09cfa473315ad`.
  Each report also records the actual Python version and verifier fingerprint.

## Scope

This validates the infrastructure and probes on known fixtures; it is not a new
coding-agent efficacy experiment. The current runner supports only the specified
single-file Python helper APIs. Container isolation does not make the in-process
test interpreter tamper-proof against deliberately malicious candidate programs.
The full limitations and runnable commands are in [the harness guide](../harness/README.md).

Next: OpenHands adapter and bounded external repair controller. SecRepoBench
integration and held-out evaluation remain later work.
