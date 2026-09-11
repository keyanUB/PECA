# Repository security harness

The harness is security-focused and dataset-independent. Security advice uses
only the public task and masked source, optionally source-bound AST evidence.
Internal verification uses generic public build-system detection, requests
AddressSanitizer/UndefinedBehaviorSanitizer instrumentation, and runs public tests
in a clean source-only container. It has no benchmark-ID or project-specific
rules. Missing build support remains an observable limitation, not task exclusion.
Instrumentation, coverage and policy-to-check binding are not guaranteed.

## Data boundaries

| Component | Available data | Excluded data |
| --- | --- | --- |
| OpenHands SDK / Advisor | Public request, masked snapshot, selected public advice | Reference code, PoCs, private metadata/results, repository history |
| Internal verifier | Public request/target and target-projected public snapshot | ARVO image, benchmark tests/metadata, private baseline report |
| Final evaluator | Sealed candidate, pinned ARVO image, upstream tests/parsers/baseline | Any path back to candidate generation or repair |

Only the source snapshot is mounted into the coding container; policy files are
separately read-only. There is no Docker socket, host credential, network access,
reference mount or `.git` history. The generic agent image is pinned to an immutable
image ID and is also used by internal verification. Never substitute a raw ARVO
evaluation image as the agent image. Public build dependencies may be incomplete;
an evaluator self-check does not establish agent build readiness.

The source adapter removes history by exporting the pinned repository and replaces
the target with the exact upstream perturbed mask. It records tracked-file edits
but replays only the target for internal verification and final scoring. Agent
edits to public tests cannot redefine the trusted check inputs.

## Generated-file-only repairs

The controller declares submission files before coding; in a completion task this
is the target file containing the generated code, even when that file existed in
the masked input. The scope is not the set of arbitrary files the agent modified.
Every arm is told this submission boundary. External repair starts from a fresh
original public snapshot with only the last submitted target replayed, discarding
out-of-scope edits and build state from the repair workspace (the original change
records remain available for audit).

During repair, `/workspace` is mounted read-only, with individual read-write bind
mounts only for the declared generated submission files. This boundary survives
container restart; paths containing symlinks, hardlinks, traversal or non-file
entries cannot become writable mounts. A post-call snapshot check independently
detects out-of-scope tracked changes. This constrains agent modifications, not
which benchmark tasks or tests are accepted.

The repair prompt explains in-place file writes, out-of-tree builds and temporary
tests in `/tmp`. It does not authorize changing dependencies or tests to make a
check pass. Findings outside the submission may still be reported by the public
verifier; location alone does not establish whether generated code caused them.
If no supported in-scope repair exists, the agent should preserve the candidate,
report the unresolved finding and finish. It must not expand its edit permissions.

## Schedule and resources

`baseline`, `policy` (Advisor-only), `verification`, and `full` use the same coding
model, shell tools and public environment. Without external repair, the default
ceiling is 120 SDK iterations and 600 seconds in one call. Repair arms can use
60 iterations/300 seconds initially and one 60-iteration/300-second repair. These
are ceilings, not targets: do not force equal cost or make extra calls to consume
unused budget. Record real coding/Advisor usage, repair counts and verification
time; discuss effectiveness and efficiency together after execution. Missing fees
are unknown, not zero. SDK estimates are not provider invoices.

The host worker atomically checkpoints SDK usage after response events and steps,
as well as writing a terminal report. A killed worker's last checkpoint contributes
only its known subtotal. Any in-flight/unreported request remains unknown, and
summary totals stay incomplete; a checkpoint never establishes successful agent
completion. Missing or partial call costs are counted explicitly. Historical runs
without these checkpoints retain their original missing usage; it is not backfilled
with invented values.

Repair depends only on a public verification failure and a present candidate
under the declared stopping policy. No reference health, task qualification,
hidden score or candidate-specific benchmark exception can enable repair. All
verification arms receive the same frozen generic profile.

The runner performs these stages strictly in order:

1. Freeze the task population, condition schedule, source/runtime/catalog hashes,
   image identities and resource ceilings. Default population: all official tasks.
2. Record all planned slots before preparation/model calls. Preparation and Advisor
   failures remain records. Complete all candidate generation and allowed repairs.
3. Seal every generation record and final candidate by hash, including unavailable
   slots. Unfinished generation cannot be sealed; candidate changes invalidate it.
4. Only after the complete-population seal, run final functionality and security
   scoring for available candidates. Scoring cannot call the agent or Advisor.
5. Summarize the full planned denominator, operational statuses and observed costs.

Directories cannot be overwritten; generation cannot resume after sealing and
hidden tests cannot be selectively retried. An interrupted experiment retains its
partial evidence. A restart needs a separately declared new experiment; report
the original attempt, not only the restart.

## Maintaining the architecture diagram

The editable Mermaid block in the [root README](../README.md#harness-architecture)
is the single source of truth for the overview diagram. Do not maintain a separate
PNG or duplicate diagram that can drift from it. The diagram covers the implemented
repository workflow; proposed mechanisms belong in design/ablation documents until
they are implemented.

| Diagram component | Implementation |
| --- | --- |
| Three CLI stages | [CLI dispatch](../harness/benchmarks/cli.py), [run](../scripts/run_experiment.py), [evaluate](../scripts/evaluate_experiment.py), [summarize](../scripts/summarize_experiment.py) |
| Freeze, repair scheduling and global seal | [Experiment controller](../harness/benchmarks/pilot.py) |
| Public task/source preparation | [Benchmark adapter](../harness/benchmarks/secrepobench.py), [source snapshots](../harness/repository.py) |
| Security policy selection | [Repository Advisor](../policy-advisor-mcp/src/policy_selector/repository.py) |
| Coding and restricted repair tools | [Agent supervisor](../harness/adapters/repository.py), [SDK worker](../harness/adapters/repository_sdk.py), [sandbox](../harness/sandbox.py) |
| Independent public checks | [Public verifier](../harness/verification/repository.py) |
| Final benchmark tests and scoring | [Benchmark adapter](../harness/benchmarks/secrepobench.py), [upstream scoring](../harness/benchmarks/upstream.py) |
| Usage records and reporting | [Usage persistence](../harness/adapters/usage.py), [reporting](../harness/benchmarks/report.py) |

When changing the workflow:

1. Update nodes and arrows in the same change as the implementation; check CLI
   names, stage order, conditional policy delivery and repair stopping rules.
2. Preserve the distinction between public verification and evaluator-private
   tests. Never draw a final-score/reference/PoC feedback edge to generation.
3. Reflect actual write permissions and keep failed/unavailable planned slots
   visible. A permission boundary is not a benchmark task-qualification gate.
4. Update the [runbook](experiment-guide.md) if commands, flags, outputs or exit
   codes change. Preview the Mermaid block in a Mermaid-enabled Markdown renderer
   and check links to the implementation files.

## Running the workflow

The [README](../README.md#run-an-experiment) provides the three commands in order;
the [runbook](experiment-guide.md) is the operational reference for setup,
parameters, outputs, exit codes and interruptions. The separate
[testbed CLI](secrepobench-testbed.md) is for model-free operator diagnostics.
No qualification directory is accepted by the formal experiment.

See [benchmark evaluation](benchmark-evaluation.md) for upstream scoring semantics,
local runtime differences and prior-exposure disclosure. This is a custom isolated
shell adapter using the native OpenHands SDK, not stock OpenHands CLI. No new
benchmark result or security-effectiveness claim accompanies this refactor.
