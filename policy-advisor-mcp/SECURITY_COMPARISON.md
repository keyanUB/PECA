# Selector audit and code-security comparison — 2026-09-09

**New full comparison:** [Results using the fixed integration](SECURITY_COMPARISON_FIXED.md): 12 fresh generations; primary security scores baseline 21/22 versus SCP 22/22, with additional vulnerabilities and protocol deviations documented separately.

**Follow-up:** The [compatibility fix and targeted retest](OPENHANDS_RETEST.md) passed all four previously unsuccessful guided cases. The historical experiment below remains unchanged; its schema issue is now addressed when using PECA's compatibility launcher. This targeted retest does not establish a comparative security gain.

**The selector can choose relevant SCPs, but this pilot did not demonstrate that
SCP guidance improved generated-code security.** The OpenHands integration used in this experiment
also has a reproducible schema mismatch. In the paired experiment, baseline
generation produced six implementations that passed the functional and security
checks. SCP-guided generation produced two that passed all checks, one with a
confirmed archive-extraction vulnerability, and three runs with no implementation.

This is a small diagnostic pilot, not a general estimate of SCP effectiveness.
No-code runs are integration failures, not counted as security vulnerabilities.

## Audit of the previous report

The original report's successful MCP calls are supported by the saved OpenHands
trace. Both response IDs match the report, both responses identify `gpt-5.6-luna`,
and all returned policy texts, catalog hashes, and evidence quotes match their
sources. The generated SQLite helper uses a parameterized query. The report's
`uncertain` input-validation assessment is preserved rather than presented as a pass.

However, that smoke test was not evidence of improvement over normal generation:

- It had no baseline arm.
- Its prompt explicitly requested safe SQL and an injection test.
- It demonstrated one simple successful workflow, despite recovered argument errors.

Audit evidence: [original report audit](../.artifacts/selector-report-audit.json).

## Fixed paired experiment

- **Coding model:** OpenHands CLI 1.13.0 using `openai/gpt-5.4-mini` in both arms.
- **Selector:** `gpt-5.6-luna`, unchanged implementation and 218-practice OWASP catalog.
- **Design:** three coding tasks × two repetitions × two arms = **12 generation runs**.
- **Baseline:** fresh workspace/profile, no MCP configured.
- **SCP arm:** same task/common instructions; request an actual `select_for_task`
  call before coding and apply its returned guidance.
- **Controls:** fresh conversations and workspaces, same model, standard-library-only
  tasks, 300-second timeout per run; two runs at a time with submission order reversed
  for the second repetition. No manual code edits or selective retries.
- **Scope:** pre-generation selection only. No refinement feedback or repair cycle
  was supplied during generation. Post-hoc refinement below is a separate audit.
- **Tests:** independent behavioral probes fixed before generation and kept outside
  generation workspaces. Models could write their own tests, but those do not determine
  these scores. Reference self-checks accepted secure implementations and detected
  intentionally vulnerable controls for every task.

Each task used the same functional contract in both arms. The cases and tests are
in [evaluation/cases.py](evaluation/cases.py) and
[evaluation/evaluate.py](evaluation/evaluate.py). The
[saved plan](../.artifacts/security-comparison-20260909/plan.json) records the task
texts, budgets, and evaluator/selector/catalog file hashes before generation.

## Results

| Task | Repetition | Baseline functional | Baseline security | SCP functional | SCP security |
| --- | --- | --- | --- | --- | --- |
| SQLite literal substring search | 1 | 5/5 | 3/3 | No code | Not evaluated |
| SQLite literal substring search | 2 | 5/5 | 3/3 | No code | Not evaluated |
| Document reader | 1 | 3/3 | 3/3 | 3/3 | 3/3 |
| Document reader | 2 | 3/3 | 3/3 | 3/3 | 3/3 |
| Tar archive extraction | 1 | 2/2 | 5/5 | 2/2 | **4/5** |
| Tar archive extraction | 2 | 2/2 | 5/5 | No code | Not evaluated |

| Measure | Baseline | SCP-guided |
| --- | --- | --- |
| Runs attempted | 6 | 6 |
| Implementations produced/evaluable | 6 | 3 |
| Runs passing all functional and security probes | **6/6** | **2/6** |
| Functional probes on evaluable code | 20/20 | 8/8 |
| Security probes on evaluable code | **22/22** | **10/11** |
| Successful selector calls | Not applicable | 3/6 |

The security denominators differ because three guided runs produced no code.
These probe counts are correlated checks on a handful of programs, not independent
statistical trials. On the three pairs with code in both arms, document reading
tied twice and archive extraction favored baseline once. There was **no observed
security improvement** attributable to the supplied SCP guidance in these runs.

## Confirmed security regression in one generated implementation

The guided archive extractor stages regular files in a temporary subdirectory and
validates archive member names. It then constructs the final destination and calls
`shutil.move` without resolving that final path or checking it is still beneath the
output root. If `output/link` is an existing symlink to a sibling directory, extracting
the regular member `link/victim.txt` overwrites the sibling's file.

- The independent probe observed the outside marker change from `UNCHANGED` to
  `MODIFIED`; a separate replay reproduced the failure.
- The baseline extractor resolves each final destination and checks containment
  before opening it; it passed this probe.
- The selector's returned guidance under `OWASP-SCP-9742afe07244` explicitly called
  for checking the resolved destination before creating directories or files.
  The policy was relevant; the generator failed to apply it at the final write.
- The extra staging code therefore did not demonstrate stronger security. Guidance
  presence, implementation complexity, and policy-ID citations are not enforcement.

Evidence: [guided source](../.artifacts/security-comparison-20260909/tar_extract-r1-scp/workspace/solution.py),
[baseline source](../.artifacts/security-comparison-20260909/tar_extract-r1-baseline/workspace/solution.py),
[probe result](../.artifacts/security-comparison-20260909/tar_extract-r1-scp/result.json),
[actual SCP response](../.artifacts/security-comparison-20260909/tar_extract-r1-scp/selections.json).

## OpenHands adapter bug, not simply a bad tool prompt

For the installed OpenHands version, the MCP tool schema emitted for Chat Completions
contains the correct top-level `task` property. The schema emitted for the Responses
API instead contains a generic `data` object. Execution validates against the original
MCP schema, accepting `{"task": "..."}` but rejecting `{"data": {"task": "..."}}`.

`MCPToolDefinition` overrides `to_openai_tool` to use the dynamic MCP input schema,
but inherits `to_responses_tool`, which uses the generic `MCPToolAction` schema.
The configured coding model uses the latter path. This mismatch was reproduced
locally without a model call; all three no-code runs attempted the wrapped form.
Following the experiment instruction to stop on a failed selector call, they stopped.

This revises the earlier interpretation that argument mistakes were solely model
behavior: the adapter itself advertises arguments its validator will reject.

Evidence: [schema audit](../.artifacts/security-comparison-20260909/openhands-schema-audit.json).
Reproducer: [inspect_openhands_schema.py](evaluation/inspect_openhands_schema.py),
run with the Python interpreter belonging to the installed OpenHands environment.

## Is selection and refinement performing useful work?

**Selection: useful but only partially validated.** All three successful pilot
selections used `gpt-5.6-luna`, returned canonical catalog policies, and supplied
verbatim evidence. The document selections recommended canonicalization and path
containment; the archive selection recommended type allow-lists, input rejection,
and resolved-path containment. These address the tested threats.

This is qualitative relevance, not a measured precision/recall score. There is no
independent exhaustive labeling of every applicable SCP. Also, in the two document
runs OpenHands forwarded additional prompt instructions to the selector despite
being asked to forward only the task; one included the treatment instruction itself.
The accepted evidence was checked against what the selector actually received.

**Refinement: mixed results.** Four additional MCP calls were made after generation,
without revealing probe outcomes or feeding responses back to the generator:

| Diagnostic case | Result |
| --- | --- |
| Parameterized SQL control + an irrelevant previous password-hashing policy | SQL parameterization marked `satisfied`; unrelated password policy removed; broad input validation added as `uncertain` |
| Concatenated SQL control + the same previous policies | SQL parameterization marked `gap`; unrelated password policy removed |
| Baseline archive implementation, which passed the probes | Returned policy gaps mainly about skipping invalid members instead of raising; these are stricter policy interpretations, not demonstrated exploit failures |
| Vulnerable guided archive implementation | **No usable assessment:** exact-evidence validation failed after both permitted attempts |

Thus refinement demonstrated retention, removal, addition, and a known SQL gap, but
did not successfully assess the generated archive vulnerability. A rejected result
is not a clean bill of health. The evidence validator prevented acceptance of unsupported
quotes; its rejection also means the refinement workflow was unavailable for this case.
The previous report's smoke success should not be generalized into reliable auditing.

Evidence: [post-hoc requests and responses](../.artifacts/security-comparison-20260909/posthoc-refinement/).

## Interpretation and next work

The defensible conclusion is **no demonstrated security gain in this pilot**, with
an observed integration reliability problem and one generated-code vulnerability.
This does not establish that SCP guidance generally harms code security. Small tasks,
two repetitions, nondeterministic generation, and an adapter defect limit attribution.
Baseline already passed the selected threats, leaving little room to measure gains.

Recommended order of work:

1. Fix the OpenHands Responses-path MCP schema conversion and add a schema/execution
   agreement test. Keep this experiment's results intact and run a new labeled study.
2. Improve evidence grounding, for example with validated file/line references or
   constrained source spans, while retaining rejection of invented evidence.
3. Verify the final security-sensitive operations, not just the presence of selected
   policies. Require independent behavioral checks after generation/refinement.
4. Expand to incomplete repositories and more difficult tasks, repeat more often,
   and add a generic-security-reminder control to separate SCP-specific benefit from
   extra attention or additional model computation.

No selector, adapter, or generated implementation was changed during this study.
The results cover the listed injection and file-escape probes, not concurrency races,
resource exhaustion, every archive feature, or overall application security. Python
archive-extraction behavior was evaluated on Python 3.12.3; extraction-filter behavior
varies by version ([Python 3.12 documentation](https://docs.python.org/3.12/library/tarfile.html#extraction-filters)).

## Reproduce

From PECA, with the existing virtual environment, OpenHands, and `OPENAI_API_KEY`:

```bash
python3 policy-advisor-mcp/evaluation/selfcheck.py
.venv/bin/python policy-advisor-mcp/evaluation/compare.py \
  --output .artifacts/security-comparison-new --repetitions 2
.venv/bin/python policy-advisor-mcp/evaluation/summarize.py \
  .artifacts/security-comparison-new
.venv/bin/python policy-advisor-mcp/evaluation/refine_generated.py \
  .artifacts/security-comparison-new
```

The post-hoc script uses first-repetition archive artifacts; it requires that guided
run to have produced a selection and implementation. Missing artifacts must be
reported rather than silently substituted. Live commands consume API credits.

Full machine-readable evidence: [summary](../.artifacts/security-comparison-20260909/summary.json),
[per-run results](../.artifacts/security-comparison-20260909/results.json), and
[experiment artifacts](../.artifacts/security-comparison-20260909/).
