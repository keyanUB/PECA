# PECA ablation study plan

Status: design only; no ablation implementation or experiment has started.
Created: 2026-09-10.

## Objective

Determine whether the Policy Advisor improves secure, functional code generation
relative to supplying the complete SCP catalog or letting the coding agent
retrieve SCPs itself. Measure the additional cost and identify where any benefit
comes from. A security-check pass without working functionality is not success.

All-SCP and SCP-RAG are ablation conditions. They do not replace or redefine the
four main experiment conditions. AST remains disabled throughout this study.

## Main experiment and ablation conditions

The main experiment uses the following display names and stable condition IDs:

| Display name | ID | Policy access | External repair |
| --- | --- | --- | --- |
| Baseline | `baseline` | No supplied SCPs | None |
| Advisor-only | `policy` | Advisor selects SCPs and provides task-specific advice in a file | None |
| Verification-only | `verification` | No supplied SCPs | At most one attempt |
| Full | `full` | Advisor selects SCPs and provides task-specific advice in a file | At most one attempt |

**Advisor-only** is the display name, replacing Policy-only. Its implementation
ID remains `policy` for compatibility with stored protocols and results.
Every condition retains the coding agent's internal
testing/debugging loop and receives final evaluation.

| Planned ablation ID | Change to policy access | Matched main comparator | Phase |
| --- | --- | --- | --- |
| `all_scp` | Supply the complete frozen SCP catalog, with no Advisor selection or generated guidance | Advisor-only (`policy`) | First |
| `scp_rag` | Agent queries the complete frozen SCP catalog through a fixed retriever; no Advisor | Advisor-only (`policy`) | First |
| `all_scp_repair` | Same All-SCP access, with the common one-repair controller | `full` | Optional follow-up |
| `scp_rag_repair` | Same SCP-RAG access, with the common one-repair controller | `full` | Optional follow-up |

The first phase compares `baseline`, `policy`, `all_scp`, and `scp_rag` without
external repair. Matched main-condition results can be reused only if they have
the same tasks, repetitions, model/settings, code, evaluator, budgets and execution
protocol. Otherwise generate fresh matched main runs. Historical results from
different budgets or policy-delivery mechanisms are contextual evidence only.

## Research questions and contrasts

1. **Advisor versus full catalog:** Does Advisor-only (`policy`) improve joint success, reduce
   irrelevant policy exposure, or lower total cost relative to `all_scp`?
2. **Advisor versus agent retrieval:** Does Advisor-only (`policy`) improve joint success relative
   to `scp_rag`, and what additional cost does it incur?
3. **Value of policy access:** How do `all_scp` and `scp_rag` compare with the
   matched no-policy `baseline`?
4. **Interaction with repair, if funded:** Do the first two contrasts persist when
   every compared condition has the same external repair mechanism and allowance?

Treat improvements, no differences, and regressions as possible outcomes. Do not
assume that more SCPs, more retrieval, or more selected policies improve security.

### Attribution limit

The current Advisor supplies both selected SCPs and LLM-written explanations,
guidance and proposed obligations. Its comparison with raw catalog or retrieval
conditions measures the whole Advisor package, not selection alone.

Before making a claim specifically about selection quality, add a secondary
`advisor_raw` mechanism control: expose only the original catalog records for
the Advisor-selected IDs, using the same renderer as All-SCP and SCP-RAG. Omit
generated rationale, guidance and obligations from this control's agent input.
Compare `advisor_raw` with raw retrieval/full-catalog conditions, and compare
`policy` with `advisor_raw` to investigate the added guidance. Freeze this extra
control before running it; it is not part of the initial minimum-cost phase.

## Policy access design

Use the existing OWASP catalog at
[`owasp-scp.json`](../policy-advisor-mcp/src/policy_selector/data/owasp-scp.json).
Freeze its content hash, policy count, source version and attribution. Neither
ablation calls Luna to select policies or rewrite them.

### All-SCP

- Supply every SCP's ID, category, original text and source link in a stable order.
- Store the full catalog in a read-only directory outside the candidate workspace.
  Provide an index and bounded pages with exact paths. Do not silently omit
  policies to fit a prompt or shell-output limit.
- Instruct the agent to review the catalog before implementation and consult it
  while coding. Reading consumes the normal agent budget.
- Record the pages/records exposed through tool observations. Report this arm as
  **full-catalog access** unless the trace demonstrates that all records were
  presented. Availability is not proof that the model read or applied everything.

This is a file-access ablation, not automatic insertion of the entire catalog into
every model prompt. A full-context injection experiment would be a separately
specified condition.

### SCP-RAG

- Index the entire same catalog. Use one SCP per retrieval record, preserving its
  original text and attribution.
- Let the coding agent form queries from the task and its repository inspection.
  Expose `search_scps(query, top_k)` and `get_scp(id)` through a bounded, read-only
  interface. MCP is a possible transport; the existing Advisor selection tool
  must not be used as the retriever.
- Start with deterministic BM25 retrieval to avoid an additional model dependency.
  Freeze the implementation, tokenizer, indexed fields, parameters and tie-breaking
  by policy ID after development calibration. Do not label a fixed retrieval
  implementation as representative of every RAG method.
- Proposed calibration settings: maximum three searches per coding call, `top_k`
  at most five, and at most fifteen distinct fetched SCPs per call. Exceeding a
  limit returns an explicit tool message. Agent iteration/time limits also apply.
- Return original SCP records, not generated recommendations. Paginate long output
  and log truncation; never silently change or drop policy text.
- In a repair-enabled follow-up, apply the same per-call limits to the repair
  call and include its retrieval in total cost and usage.

These retrieval limits are proposed settings, not frozen experimental parameters.
Check them on development tasks before finalizing the execution manifest.

## Controls and budgets

Within each contrast, hold the following constant:

- Coding model `openai/gpt-5.4-mini`, its effective settings, SDK, tool behavior,
  sandbox image and source snapshot. The Advisor reference uses `gpt-5.6-luna`.
- Task instructions and common instruction to preserve functionality and run useful
  tests. Only policy-access instructions and necessary retrieval tools differ.
- Policy source, evaluator version, functional/security checks, repair eligibility,
  feedback format and candidate-projection rules.
- AST off; no gold fixes, hidden PoCs, CWE labels or hidden evaluation logs in
  prompts, policy queries, indexes or repair feedback.

Use the current repository protocol's per-call ceiling of **60 iterations**.
Nonrepair conditions receive one call (60 total); repair conditions receive one
initial call and at most one repair (60+60, 120 total). Time ceilings remain
600 seconds per condition, split 300+300 for repair conditions. These are unequal
iteration ceilings across conditions, not equal realized costs or dollar caps;
report that resource difference explicitly in comparisons.

Policy selection, indexing, retrieval and evaluator overhead must be measured
separately and included in the reported total. Record both actual shared/cached
cost and estimated standalone deployment cost if advice or indexes are reused.

Use the same read-only file protection and shell recovery behavior throughout.
File delivery is not itself a fix for broad shell searches and does not make
retrieved text free of model-token cost.

## Evaluation and metrics

Primary outcome: **joint success** per planned run, requiring normal agent
completion, a healthy final evaluator, all required functional checks passing,
and all designated security checks passing. This is success within the tested
scope, not proof that the implementation has no vulnerabilities.

Report separately:

- Functional pass, security pass, completion rate, and failures by task/project.
- Operational errors, iteration/time exhaustion, remaining completion markers,
  shell recovery events, and evaluator infrastructure failures.
- Initial versus repaired outcomes, repair attempts, successful repairs and
  functional regressions in the repair-enabled phase.
- Coding/advisor token usage and API cost, retrieval latency, index/setup cost,
  agent/evaluator time, and missing usage records. Missing cost is not zero.
- Retrieval queries, returned/read SCP IDs, ranking, duplicate results, exposed
  policy-text volume, file-read evidence and whether the agent used retrieval.

Keep all planned slots in operational summaries; report evaluator-unavailable
cases separately instead of labeling them code vulnerabilities. Never drop failed
attempts or rerun selected conditions until they pass.

Optionally perform a blinded review of policy relevance and corresponding code
changes, using a predefined rubric. Policy mentions and retrieval counts alone
are not security outcomes; do not claim precision/recall without reviewed labels.

## Readiness gates and execution sequence

1. **Stabilize the repository pipeline on synthetic fixtures.** Confirm policy-file
   access, recoverable shell limits, completion and repair without tuning on
   benchmark tasks or hidden outcomes. Record prior exposure honestly.
2. **Keep environment diagnostics separate.** Reference self-checks must not filter
   benchmark inputs, alter original tests or become agent/Advisor feedback.
   Validate PECA's own verifier logic using independent synthetic controls.
3. **Implement the two policy-access adapters.** Check catalog completeness,
   deterministic retrieval, output limits, read-only access, isolation and logging.
   Use task/context information only; hidden answers must stay inaccessible.
4. **Freeze the population before observing outcomes.** Full benchmark evaluation
   keeps every official task. Any smaller budgeted subset must be declared in
   advance without reference-health or result-based selection, and labelled as
   partial coverage. Preserve each planned repetition and condition, including
   preparation, generation and scoring failures.
5. **Seal then score.** Finish all planned generations and repairs before hidden
   evaluation. Preserve the schedule and candidate hashes. Record actual costs
   rather than forcing equal spending, and compare effectiveness and efficiency.
6. **Declare future studies separately.** Preselect genuinely unexposed data, a
   sample-size justification, uncertainty analysis and a spending limit before
   running the confirmatory study. Add repair-enabled ablations or `advisor_raw`
   only with a new frozen protocol.

The execution manifest must record exact tasks/split, repetitions, order seed,
all model and package settings, code/image/catalog/index hashes, query limits,
policy rendering, shared-cache rules, budgets, independent environment diagnostics, and the
rule for handling infrastructure failures. No benchmark run is authorized or
started by creating this plan.

## Analysis and decision rules

Compute paired wins, losses and ties for the predefined contrasts on the same
task/repetition slots. Report per-project results as well as aggregate joint
success and cost. Repetitions on one task are correlated; a larger study must use
task/project-aware uncertainty estimates rather than treating every run or check
as an independent sample.

If a cheaper condition matches the Advisor on measured outcomes, report the lack
of demonstrated incremental value. If the Advisor improves outcomes, examine
whether the result survives functionality checks, operational failures and cost
accounting. If completion remains unreliable, prioritize the execution pipeline
and keep the study at the feasibility stage. Do not add AST to rescue a weak result.

## Artifacts and current status

This directory currently contains only this plan. All-SCP and SCP-RAG remain
unimplemented. The main runner and historical result files are unchanged by this
document.

When executed, keep the active protocol, raw traces, policy-access records,
candidates and machine-readable results under `.artifacts/ablation-study/<run-id>/`,
excluded from Git. Publish a concise report here that records the frozen manifest
hash and evidence availability. Do not commit credentials or create placeholder
results, duplicate reports or abandoned experiment versions.

Related context:

- [Repository harness and current budgets](../docs/repository-harness.md)
- [Benchmark evaluation boundary](../docs/benchmark-evaluation.md)
- [Pre-run correctness review and fresh-evidence gates](../docs/pre-run-review.md)
