# Versioned SecRepoBench development evaluator

`upstream-v1` preserves the original PECA pilot behavior. The explicit
`qualified-v2` variant makes two scoped development corrections. Its name is a
version label; only recorded repeated reference results establish task qualification.
This is a PECA evaluator variant, not an official upstream benchmark score.
The [milestone report](ast-milestone-report.md) records task 910 qualifying in three
repetitions and task 1065 remaining unqualified. The ASLR variant is diagnostic;
it did not resolve MemorySanitizer startup instability.

For task 910, only the developer test `CheckProofingIntersection` is corrected:
creation failure returns zero, and successful creation/deletion returns one,
consistent with the surrounding test runner's success convention. The literal
old block must occur exactly once or evaluation fails. The target implementation
and hidden PoC are unchanged. The patch runs only in developer evaluation, never
in the coding workspace or hidden security evaluation.

For task 1065, evaluator commands run beneath `setarch x86_64 -R`. This disables
ASLR for that process and its descendants to address old MemorySanitizer runtime
instability. It does not modify host sysctls, replace sanitizer checks, alter the
candidate, or add retries. Secure and vulnerable references receive the same
execution setting. The existing Docker seccomp/capability configuration is retained;
a platform that forbids this operation must report an error rather than silently
relaxing isolation. Results describe this controlled sanitizer environment.

Every result records the evaluator revision, evaluator implementation hash,
correction IDs, image ID and candidate hash. Build failures now retain `config.log`
when available. Earlier reports and raw artifacts remain unchanged.

## Repeated qualification

```bash
.venv/bin/python -m harness.benchmarks.qualify \
  --source .artifacts/sources/SecRepoBench \
  --output .artifacts/reference-v2 --evaluator qualified-v2 --repetitions 3
```

The plan fixes the image IDs and evaluator fingerprint before checks run. There
are no automatic retries. In **every** repetition, qualification requires the secure
reference to pass both developer and hidden checks, and the vulnerable reference
to fail the hidden check. All attempted results are retained, including errors.
Changing the evaluator during qualification aborts the run.

Corrected pilot evaluations require repeated reference results. The pilot checks
reference source hashes, image identity and evaluator identity, and recomputes
qualification from all rounds rather than trusting a stored success flag.
The original single-round artifacts remain usable only with `upstream-v1`.
