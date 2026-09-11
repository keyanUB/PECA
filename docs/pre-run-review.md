# Pre-run review — fairness boundary refactor

No benchmark experiment or model comparison has been run for this refactor.
The previous results, control/qualification records, generated testbeds, obsolete
reports, configs and temporary outputs remain retired. Only the pinned benchmark
source is retained under `.artifacts/`.

## Current guarantees enforced in code

- One active benchmark adapter; no task-specific test fixes, extra tests, ASLR
  overrides or PECA project whitelist. Exact upstream perturbed inputs and parsers.
- Environment self-checks do not determine task eligibility and are not read by
  generation. Every frozen task/condition slot remains in results and denominators.
- Internal security verification executes only public source in the isolated
  public image. ARVO logs, reference implementations and private baselines cannot
  enter the automatic repair path.
- All planned generation ends before a complete-population candidate hash seal;
  final scoring requires the seal and cannot start new generation or retries.
- Default coding ceilings are declared consistently. Actual costs need not match;
  observed usage, failures and missing cost data are preserved for efficiency analysis.
- Earlier benchmark exposure is disclosed. Removing old special cases is not a
  claim that the evaluation dataset was never seen.

## Remaining limitations

Software regression tests do not prove full benchmark runtime readiness or an
absence of all bugs/leakage. The public image may lack project dependencies, the
generic sanitizer verifier has limited build/coverage support, and policy-to-check
binding is incomplete. ARVO's original network/privilege assumptions may conflict
with the recorded local sandbox limits. Report those errors without excluding
tasks or treating them as demonstrated vulnerabilities.

The isolated shell uses the OpenHands SDK rather than stock OpenHands CLI. Actual
model settings and tool/SDK metadata are recorded per call. Prior manual exposure
and possible model pretraining contamination cannot be undone or ruled out here.

Use synthetic fixtures for future harness development. Do not add benchmark-task
rules, tune policies from hidden results, invent replacement tests, or use
self-check outcomes as a task selector. Any later protocol change must be frozen
before new generation and disclosed alongside earlier attempts.

## Software verification on 2026-09-11

`PYTHONDONTWRITEBYTECODE=1 PECA_TEST_DOCKER=1 .venv/bin/python -B -m pytest harness/tests policy-advisor-mcp/tests -q -p no:cacheprovider`
completed with **213 passed**. Docker cases use synthetic fixtures; SDK loop tests
use scripted steps and MCP tests do not make model calls. Python syntax checks,
protocol/document checksums and `git diff --check` also passed. The pinned upstream
checkout remains unmodified, and `.artifacts/` contains only its source directory.

These checks are software evidence, not benchmark runtime qualification or efficacy
evidence. See [repository harness](repository-harness.md) and
[benchmark evaluation](benchmark-evaluation.md) for the executable boundaries.
