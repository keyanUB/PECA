# Experiment runbook

This guide covers the formal repository experiment CLI. For the architecture and
three-step example, start with the [README](../README.md). For testing submitted
code without models, use the [testbed guide](secrepobench-testbed.md).

## Prerequisites

Run from the PECA repository root on Linux or Ubuntu under WSL with Python 3.12+
and a working local Docker daemon. The formal harness uses Linux process/resource
controls; the interactive launcher's broader platform support does not establish
experiment compatibility.

Prepare a host Python environment if one does not already exist:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e './policy-advisor-mcp[dev]'
```

The host environment runs the controller, Advisor client and regression tests.
The `dev` extra installs test dependencies. Do not recreate an environment in the
middle of a frozen experiment. A separate Python interpreter supplied through
`--openhands-python` must have the compatible OpenHands SDK installed; an
interactive CLI executable alone is not the interpreter path.

Before generation, make the following available:

- The pinned, unmodified SecRepoBench checkout; see
  [evaluation semantics](benchmark-evaluation.md) for its revision.
- The public agent image and each declared task's ARVO image. Images are resolved
  to immutable IDs during freezing; scripts do not pull them automatically.
- `OPENAI_API_KEY` securely set in the host environment for model calls. Never
  place it in command-line arguments, candidates or committed configuration.

Evaluation requires the same frozen implementation, benchmark revision, images
and resource settings. It does not need model credentials. Summarization reads
local evidence only; it does not need Docker, the benchmark checkout or an API key.
Missing dependencies remain observable failures, not reasons to exclude tasks.

## Stage order

| Order | Entry point | Input | Completion evidence |
| --- | --- | --- | --- |
| 1 | `scripts/run_experiment.py` | Public task population and new experiment directory | `seal.json`, `generation-complete.json` |
| 2 | `scripts/evaluate_experiment.py` | Frozen experiment and benchmark checkout | `scoring-complete.json` |
| 3 | `scripts/summarize_experiment.py` | Existing experiment evidence | `summary.json`, `summary.md` |

Step 1 freezes configuration before model calls, runs generation and internal
public security/build verification, performs permitted repairs and seals every
planned slot. It never invokes final benchmark evaluation. Repairs can modify
only generated submission files; other source files and tests remain read-only.

Step 2 verifies the complete-population seal and frozen runtime before final
benchmark evaluation. It cannot invoke generation, Advisor selection or repair.
Final results must never be fed back to those components.

Step 3 verifies existing protocol, candidate and completed-result hashes. It
reports every planned slot, separating benchmark pass, agent completion and actual
efficiency. It does not rerun any test. The [README](../README.md#run-an-experiment)
contains the commands in execution order.

## Parameters

| Script | Parameter | Meaning |
| --- | --- | --- |
| Run | `--source` | Required pinned benchmark checkout |
| Run | `--output` | Required new experiment directory; must not exist |
| Run | `--tasks` | Optional predeclared task IDs; omission means **all official tasks** |
| Run | `--conditions` | Optional subset of `baseline policy verification full`; default is all four |
| Run | `--openhands-python` | SDK interpreter; default is `~/.local/share/uv/tools/openhands/bin/python` |
| Run | `--max-external-repairs` | Default 1; changes the declared repair and coding ceilings |
| Run | `--ast-context` | Optional public-source AST evidence for Advisor selection; off by default |
| Run | `--evaluator` | Frozen evaluator revision; currently only `benchmark-v1` |
| Evaluate | `--source`, `--experiment` | Required checkout and sealed experiment; no task/model/budget overrides |
| Summarize | `--experiment` | Required evidence directory |
| Summarize | `--output` | Optional fresh report prefix; default is `EXPERIMENT/summary` |
| Summarize | `--allow-partial` | Explicitly permit a diagnostic report before scoring completes |

All scripts accept `--help`. Choose the task population before observing results;
a declared subset is not full-benchmark evidence. Omitting `--tasks` can incur
substantial model/runtime costs. The current runner uses one repetition per
task/condition and a frozen shuffled order.

The default non-repair budget is 120 SDK steps / 600 seconds. Repair arms have
60 steps / 300 seconds initially, plus at most one 60-step / 300-second repair.
These are ceilings, not spending targets. Actual Advisor, coding and verification
costs need not match across conditions. See [resources and accounting](repository-harness.md#schedule-and-resources).

## Outputs and interpretation

`protocol.json` records task selection, conditions, model settings, source/runtime
hashes, image identities and limits. Per-slot `generation.json` records agent
status, changes, internal checks and repair history; the global `seal.json` binds
all planned generation records and available candidates.

Final evaluation adds per-slot `result.json` and evaluator-private logs, updates
`results.json`, and writes `scoring-complete.json` with result hashes. Slots with
preparation errors, timeouts or unavailable candidates remain represented.

The summary JSON contains per-slot outcomes, condition aggregates, status counts,
observed usage and timing. Markdown is a shorter overview. A successful benchmark
candidate is not necessarily a normally finished agent: `secure_pass` and
`joint_pass` are separate fields. A missing/unavailable score is not evidence of
a vulnerability. Consult [the exact scoring semantics](benchmark-evaluation.md).

SDK costs are estimates, not invoices. Interrupted calls contribute only their
last recorded usage subtotal; in-flight or missing usage remains unknown. Advisor
selection is shared across policy/full and counted once in actual totals. Preserve
new artifacts, including failed attempts, under `.artifacts/` (Git-ignored).

## Exit codes and failures

| Exit | Meaning for these experiment scripts |
| --- | --- |
| `0` | The requested stage completed its records; not a claim that all agents/tests succeeded |
| `1` | Stage, dependency, integrity or output error |
| `2` | Invalid CLI arguments |
| `130` | Interrupted execution |

Progress is sent to stderr. Successful execution emits one JSON status object on
stdout; handled operational errors are reported on stderr. The model-free testbed
has its own pass/fail exit-code contract; do not interchange the two.

- Run stages sequentially. Exclusive start markers prevent duplicate concurrent
  generation/evaluation; there is no `--force`, overwrite or automatic resume.
- Do not edit code, configuration or candidates between generation and evaluation.
  Changed hashes or an incomplete seal block final evaluation before hidden tests.
- If generation stops before sealing, do not evaluate only its completed subset.
  If evaluation is interrupted, do not selectively retry failed/missing scores.
- Preserve the original attempt. A rerun requires a separately declared new
  experiment directory; never delete markers to bypass lifecycle checks.
- A summary refuses to overwrite either existing output file. Use a fresh prefix
  rather than replacing prior evidence.

For a read-only diagnosis of an unfinished attempt, explicitly request a partial
report with a distinct output prefix:

```bash
.venv/bin/python scripts/summarize_experiment.py \
  --experiment .artifacts/NEW-EXPERIMENT \
  --allow-partial --output .artifacts/NEW-EXPERIMENT/progress-report
```

This report is labeled diagnostic, not final. It does not resume generation or
evaluation. Once the original stage completes normally, the default `summary`
prefix remains available for the final report.

## Compatibility and other workflows

The combined `python -m harness.benchmarks.pilot run` CLI action is removed.
Low-level `freeze`, `generate` and `score` actions remain for compatibility; prefer
the three scripts above. `scripts/summarize_repository_pilot.py` delegates to the
same reporting implementation and also requires `--allow-partial` for unfinished
experiments.

The [interactive OpenHands launcher](openhands-launcher.md) is for ordinary agent
work, not this four-condition protocol. The [model-free testbed](secrepobench-testbed.md)
supports operator diagnostics; its ARVO outputs, including unit-test diagnostics,
must not enter the agent's repair loop. Neither tool replaces the formal global
sealing barrier.
