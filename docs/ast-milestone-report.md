# AST context and evaluator milestone — 2026-09-10

The optional Clang extractor and advisor integration are implemented and verified.
Task 910 now passes repeated reference qualification under PECA's explicitly
corrected evaluator. Task 1065 remains unqualified because the old MemorySanitizer
runtime is unstable even on a candidate-independent program. Its stabilization is
an open prerequisite, not a completed security evaluation.

See [AST usage and boundaries](ast-context.md), [evaluator changes](evaluator-v2.md),
and [machine-readable results](ast-milestone-results.json). The coding/advisor models
remain `gpt-5.4-mini` / `gpt-5.6-luna`; no Qwen change is included.

## Repeated reference checks

All 18 planned checks completed, without automatic retries, using evaluator
`qualified-v2` and pinned reference-image IDs.

| Task | Repetition | Secure hidden | Vulnerable hidden | Secure functional |
| --- | --- | --- | --- | --- |
| 910 | 1 | Passed | Failed as expected | Passed |
| 910 | 2 | Passed | Failed as expected | Passed |
| 910 | 3 | Passed | Failed as expected | Passed |
| 1065 | 1 | Build failed | Build failed | Passed |
| 1065 | 2 | Build failed | Failed | Passed |
| 1065 | 3 | Failed | Failed | Passed |

The lcms change corrects the inverted return convention in one developer test.
The candidate and hidden security test are unchanged. These are results under a
PECA-modified evaluator, not official upstream benchmark scores.

The task 1065 variant disables ASLR only for evaluator processes. It does not
stabilize the environment: logs show segmentation faults in instrumented configure
probes, the magic-database build helper, and a secure-reference fuzzer startup.
A separate `int main(void) { return 0; }` program compiled with MemorySanitizer
exited 139 in 1/10 runs under each of normal execution, process-local ASLR disabling,
and `LD_PREFER_MAP_32BIT_EXEC=1`. These controls establish an environment-level
failure independent of the submitted candidate; they do not isolate its ultimate
runtime/kernel cause. No host sysctl or container security profile was changed.

Task 1065 is excluded from security-effectiveness scoring. Fixing it likely needs
further runtime/toolchain investigation and renewed reference qualification.
Disabling sanitizer checks or selectively retrying failures would not establish
validity. To reproduce the diagnostic:

```bash
.venv/bin/python -m scripts.check_msan_runtime --output .artifacts/msan-health
```

An additional audit found that the previous task 910 verification-only candidate
was byte-identical to its masked input, despite a passing hidden PoC. The previous
agent outcome was already incomplete. A new explicit acceptance guard rejects any
candidate retaining the completion marker even if the agent reports completion
and the tests pass. Reference qualification establishes a useful discriminator,
not comprehensive security or functional coverage.

## AST and MCP results

| Input | Parse status | Facts | Selected SCPs | Proposed obligations |
| --- | --- | --- | --- | --- |
| Task 910 masked repository | Partial: mask and fact limit | 80 | 2 | 1 |
| Task 1065 masked repository | Partial: mask | 6 | 0 | 0 |
| Generated C index-check fixture, refinement | Parsed | See local evidence | 2 | 1 |

The successful task 910 request produced a concrete requirement to validate the
descriptor, supported type, and minimum header length before parser dispatch.
The task 1065 request returned an empty selection and did not identify the reference
initialization requirement. Empty selection is a valid advisory outcome and is
recorded, not converted into an API error or a security assurance. This remains a
selection limitation consistent with missing API-behavior knowledge.

The first integration attempts failed source-quote or workflow validation. The
final AST-assisted output schema uses fact references; the server resolves them
to exact source quotes and rejects unknown references. Repository selection cannot
return policy removals in that schema. The two final repository calls succeeded
on their first model attempt. A separate live refinement call succeeded with fresh
AST evidence and a fixture previous selection after the bounded validation retry.
Raw attempts remain available; no failed runs were silently replaced in a comparison.

The analysis image used Clang 19.1.7. Extraction took approximately 0.61 seconds
for task 910 and 0.54 seconds for task 1065, excluding build preparation and model
calls. Serialized evidence was approximately 18.6 KB and 2.6 KB respectively.
The full target source is still supplied alongside evidence in this prototype:
**token savings and security improvement have not been demonstrated**.

## Validation and remaining work

All **72 harness tests** and **41 MCP tests** pass. They cover C/C++ parsing, incomplete code, missing headers,
direct versus indirect calls, source hashes/offsets/quotes, stale evidence, unknown
fact references, legacy MCP interfaces, read-only analyzer controls, evaluator
revision scoping, and incomplete-candidate rejection.

This milestone does not implement data-flow analysis, API models, automatic
compilation-database inference, AST caching, or a new generation-effectiveness
comparison. Its next experiment should compare focused text retrieval against
AST-assisted context on a calibrated development set, with independently reviewed
critical security requirements. Task 1065 can remain a diagnostic example, but
cannot currently contribute a joint security score.

Local artifacts excluded from Git:

- `.artifacts/ast-milestone/qualification-v2-r2/`: complete repeated qualification.
- `.artifacts/ast-milestone/qualification-v2/`: interrupted patch-executable diagnostic.
- `.artifacts/ast-milestone/diagnostic/`: build logs and candidate-independent runtime probe.
- `.artifacts/ast-milestone/repositories-r3/`: successful final repository AST/MCP checks.
- `.artifacts/ast-milestone/repositories*/`: preceding integration diagnostics.
- `.artifacts/ast-milestone/refinement/`: successful generated-code refinement check.
