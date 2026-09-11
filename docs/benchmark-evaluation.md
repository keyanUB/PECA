# Benchmark evaluation boundary

SecRepoBench is an evaluation dataset, not the source of security-harness rules.
The only active adapter revision is `benchmark-v1`. Earlier evaluator revisions,
task-specific test patches, extra task tests, project whitelists and process-ASLR
overrides have been removed. They cannot be selected through the CLI.

## Inputs and scores

The upstream checkout must remain clean at
`7ca5c4a7e908f8013e7b9ae624ba0d96f8c6ec76`. The official task population comes from
`assets/ids.txt` (318 tasks); the default input is the original `mask_perturbed`
file. No reference-based eligibility filter, replacement mask or task rejection
rule is introduced by the security harness. An adapter/environment failure is
recorded for every affected planned slot, not silently removed from the study.

Unit-test recipes come directly from upstream `assets/projects.py`. The adapter
only decodes their outer-shell transport escaping. It does not replace recipes,
change tests, or equate a trailing shell exit of zero with passing tests.

The exact pure parser definitions are loaded from upstream `tools/evaler.py`.
Original stdout and stderr bytes are preserved separately. Functionality follows
`tools/report_analyzer.py`: every test in the upstream reference passing-test set
must appear in the candidate passing-test set. Empty reference sets are preserved
and their size is reported; PECA does not invent a replacement score or filter.
The private baseline report is opened only for final functional scoring.

`secure_pass` follows upstream secure-pass@1: functional subset success and the
security parser's exact `pass` label. In particular, `pass (false alarm)` is not
silently changed to `pass`. `joint_pass` separately requires normal agent
completion and a present completion; it is not the official benchmark metric.
Errors, unavailable results and unfinished slots remain explicit. Their absence
of a demonstrated success contributes no numerator, while the planned denominator
remains fixed. They are not evidence of a code vulnerability.

## Environment fidelity and limitations

Use the ARVO image's native working directory. Preserve its existing build setup
with stash/checkout/apply at the pinned revision. Use upstream eight-job build
parallelism and up to three fixed `arvo compile` attempts within one build budget.
Do not add task-specific dependency repairs or retry failed candidates selectively.

The local executor is intentionally bounded: offline networking, 8 GiB memory,
eight CPUs, 1,024 processes, 1,200 seconds for unit/build stages, 60 seconds for the
PoC, bounded output, and restricted capabilities. These are recorded local runtime
differences from upstream Docker defaults, not claims of byte-for-byte runtime
equivalence. Network-dependent setup or privileged image setup can fail. Preserve
those failures and the full population; do not report a reduced supported subset
as the complete benchmark.

ARVO containers have no host workspace mounts. All their outputs, including unit
and build logs, are evaluator-private: candidate execution inside an image that
contains references/PoCs could print private files. Such output must never become
agent, Advisor or repair input.

## Self-check versus qualification

`python -m harness.benchmarks.selfcheck` is an optional, model-free operator
diagnostic. It tests supplied secure/vulnerable controls and retains every planned
diagnostic, including failures. It does not produce an eligibility decision.
The generation runner neither accepts nor reads self-check results. The old
qualification CLI/gate has been removed; it was a PECA rule, not an OpenHands
requirement. Do not use self-check outcomes to select tasks or tune the harness.

## Exposure and claims

Earlier development inspected benchmark tasks and results. Deleting special cases
and old outputs does not undo that exposure or establish an untouched held-out
set. Current protocols disclose it. Software isolation can block known runtime
leakage paths; it cannot prove absence of model pretraining contamination or
guarantee absolute experimental fairness.
