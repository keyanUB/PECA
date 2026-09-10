# Simpler-design experiment v2

Status: **implementation qualified; execution requires a matching frozen manifest**.
This is a small development experiment, not a confirmatory benchmark study. Final
tests are separate from the development suite used for repair feedback. No generation
runs may start until the execution gates below are satisfied and a matching
execution manifest is frozen. The 36-run comparison has not started.

The machine-readable design is [simple-design-protocol.json](simple-design-protocol.json),
with its byte-level checksum in `simple-design-protocol.sha256`. Version 2 removes
historical audit/report references during cleanup and records the implemented
suites. Tasks, conditions, models, budgets and run order are unchanged. Current
runtime source hashes belong to the execution manifest. Record substantive design
changes in a new version before generation.

## Question and scope

Does the current combination of SCP prompt advice and fixed external checks with
bounded repair improve useful secure generation relative to the agent's own loop?
Does policy advice add benefit beyond the same fixed external checks?

Use the existing three Python task prompts (SQL search, document reading and
archive extraction), copied exactly into the protocol. These tasks have been used
in PECA development before; they are not held-out projects. Three repetitions per
task and four conditions give 36 planned generation runs. This is a small
descriptive pilot with limited task diversity and no statistical power claim.

AST stays disabled. No new obligation-to-check templates, automatic bindings,
post-generation advisor refinement, extra verifier LLM or agent-test scoring is
introduced. Existing baseline checks always run as specified; their selection
does not depend on the advisor output.

## Conditions

| Condition | SCP advice | External development feedback and repair |
| --- | --- | --- |
| baseline | No | No |
| policy | Yes | No |
| verification | No | Up to one repair |
| full | Yes | Up to one repair |

Every condition uses the same isolated OpenHands SDK agent, model, public task,
tools and instruction to write and run useful tests. It retains its internal
testing and debugging. Use fresh workspaces/conversations per run. Repair uses
a fresh conversation with the retained workspace, original task, original advice
when applicable and bounded development failure evidence. This intervention also
changes conversation staging; do not attribute its effect solely to test content.

The controller calls the existing MCP `select_for_task` with only the exact task
argument, matching the simpler single-file path. One response per task/repetition
is cached and shared by policy/full (nine planned MCP requests). The selector's
existing bounded validation retry stays unchanged. Do not reroll advice based on
its contents. An empty valid selection remains a recorded treatment outcome.
Selection failure marks the affected two arms `advisor_error`; retain their
planned slots, and let the non-policy arms proceed. There is no silent fallback.

Advice is untrusted prompt data. It does not configure executable checks, confer
privileges or certify policies. Do not claim policy-obligation coverage from
passing the generic family suite.

## Budget, order and stopping

- Coding model: `openai/gpt-5.4-mini`; advisor: `gpt-5.6-luna`.
- Each run has a ceiling of 30 SDK iterations and 300 seconds of agent runtime.
  Baseline/policy receive one call with that ceiling. Verification/full receive
  at most 20 iterations/200 seconds initially, then at most 10 iterations and
  the remaining runtime, capped at 100 seconds, for one repair.
- Trigger repair only after the agent finishes and a development check reports
  a demonstrated failure. Missing evidence, infrastructure errors, timeouts or
  cleanup uncertainty do not become coding feedback. Record incomplete candidates
  diagnostically, but they cannot count as joint successes.
- The existing verifier has a 30-second candidate-execution timeout. Container
  setup/cleanup overhead is measured separately and is not a hard run deadline.
  The final-suite timeout and tooling must be pinned and qualified in the later
  execution manifest; do not infer runtime settings from v1's null fields.
- Advisor requests have a 150-second ceiling. Advisor and verifier time/cost are
  additional to agent budgets. Equal ceilings do not imply equal actual spending.
- Run serially. Shuffle the nine task/repetition blocks and then the four arms
  within each block with seed 20260910; the exact 36-row order is stored in JSON.
  The seed controls scheduling, not deterministic model output.
- Preserve every attempted run. No selective retry, candidate cherry-picking or
  extra repair based on final results. If an infrastructure fault requires a
  restart, retain the attempt and issue a versioned restart manifest before rerun.

## Verification separation and execution gates

Development feedback uses all existing family checks in
`harness/verification/probes.py`. Baseline/policy candidates receive the same
development assessment after completion, but its results never return to them.
All four arms receive the same independent final assessment after their last
permitted coding call. Freeze all final candidates before computing final scores.

The following are required before experimental generation:

1. Implement a separate final evaluator and document each check's behavioral
   oracle, scope and relationship to development checks. Use different inputs
   and fixtures, with functional cases that reject trivial all-reject/no-op code.
   Shared threat classes are expected; do not call them new vulnerability classes.
2. Qualify both suites with safe, vulnerable and deliberately incomplete/trivial
   development controls in three consecutive recorded rounds. Safe controls must
   pass required functional/security checks; faulty controls must fail the checks
   intended to detect them; trivial controls must fail joint acceptance. Candidate
   errors and infrastructure faults must remain distinct. Never tune using newly
   generated experimental candidates or hidden benchmark answers.
3. Add minimal Python four-arm runner glue using the existing isolated agent
   boundary. Agent/advisor inputs must exclude final test files, reference code
   and evaluation artifacts; enforce this via mounts and tool scope. Preserve
   candidate hashes, metadata and all budget decisions.
4. Validate orchestration with deterministic adapters and a separately labelled
   live smoke task outside the 36-run matrix. Instrument SDK iterations, model
   usage, elapsed time, actual repair triggers and errors.
5. Freeze a complete execution manifest: protocol digest, clean runtime source
   bundle, exact agent prompts/settings, package versions, image IDs, task and
   suite hashes, qualifying-control reports and smoke evidence. Enforce those
   hashes at run time. Changes require a new manifest.

The current Python experiment runner uses the isolated SDK adapter with Python
task context and a separate final evaluator. Its language label does not limit
the advisor's input language. The deferred repository-security design is not
required for these gates.

## Outcomes and interpretation

Primary outcome: a completed, valid candidate passes every required independent
final functional and security check with healthy evaluation and confirmed cleanup.
Report successes out of all planned slots, alongside the full status breakdown.
Missing candidates, incomplete work, advisor errors and infrastructure failures
remain visible as separate categories; they are not automatically vulnerabilities.
Also report success among evaluable completed runs with its denominator.

Secondary outcomes include independent functional/security pass rates, individual
check failures, initial-to-final development changes, repair triggers and success,
regressions, selected policy IDs/counts, empty selections, token usage, SDK-reported
cost estimates, agent/advisor/verifier time and missing accounting fields. Security-
only pass rates must be read alongside functionality, because all-reject controls
pass the current security probes. SDK costs are estimates, not billing records;
do not infer unknown advisor dollar costs as zero. Report both actual cached
advisor cost and the stand-alone per-policy-run allocation for comparison.

Compare policy minus baseline (advice), verification minus baseline (external
loop), full minus verification (incremental advice), and full minus policy
(incremental external loop), stratified by task and paired by repetition. Show
raw counts and differences rather than significance claims from this small pilot.
Policy/full share cached advice, so their advisor outcomes are correlated.

Review traces using fixed categories: relevant advice or missing requirement;
guidance followed/ignored/unclear; detected versus missed failure; successful or
regressing repair; incomplete agent; infrastructure failure. Label single-reviewer
judgments as qualitative. Do not use an LLM's opinion as the security outcome.

If improvements occur only on development checks, report repair of known checks,
not independent security generalization. If verification helps but full adds no
observed benefit, evidence supports the external loop but not incremental advisor
value in this sample. A null result on three tasks does not prove no future value.

## Repository follow-up

After the Python pilot, task 910 can demonstrate repository feasibility under
the versioned evaluator after fresh qualification. Its external repair feedback
remains functional; do not claim a C/C++
policy-to-security-check implementation. Task 1065 remains diagnostic until its
runtime qualifies reliably. Broader repository effectiveness and AST ablations
require separate later protocols.
