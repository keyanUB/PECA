# Simpler-design comparison

Completed 36 scheduled runs: three tasks × three repetitions × four conditions. AST was disabled.
Coding model: `openai/gpt-5.4-mini`. Policy advisor: `gpt-5.6-luna`.
Final scores were computed after generation and repair finished. All primary outcomes below were recomputed from candidate-bound verifier reports.

## Outcomes

All outcome columns use nine planned slots per condition. Functional/security columns also require the agent to finish; incomplete candidates remain diagnostic.

| Condition | Finished | Functional | Security | Joint success | Repairs / successful | SDK coding cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 9/9 | 9/9 | 7/9 | 7/9 | 0 / 0 | $0.2554 |
| policy | 9/9 | 9/9 | 9/9 | 9/9 | 0 / 0 | $0.3877 |
| verification | 9/9 | 9/9 | 9/9 | 9/9 | 1 / 1 | $0.3191 |
| full | 9/9 | 9/9 | 9/9 | 9/9 | 0 / 0 | $0.4438 |

## Joint success by task

| Task | Baseline | Policy | Verification | Full |
| --- | ---: | ---: | ---: | ---: |
| sql_search | 3/3 | 3/3 | 3/3 | 3/3 |
| document_read | 3/3 | 3/3 | 3/3 | 3/3 |
| tar_extract | 1/3 | 3/3 | 3/3 | 3/3 |

## Paired comparisons

| Treatment minus control | Wins | Losses | Ties | Joint difference |
| --- | ---: | ---: | ---: | ---: |
| policy − baseline | 2 | 0 | 7 | +22.2 pp |
| verification − baseline | 2 | 0 | 7 | +22.2 pp |
| full − verification | 0 | 0 | 9 | +0.0 pp |
| full − policy | 0 | 0 | 9 | +0.0 pp |

These are descriptive differences across nine task/repetition pairs, not statistical significance estimates.

## Failures and incomplete work

| Run | Agent status | Final failed checks |
| --- | --- | --- |
| tar_extract-r2-baseline | completed | final.tar_extract.directory_link_chain, final.tar_extract.leaf_link_chain |
| tar_extract-r3-baseline | completed | final.tar_extract.directory_link_chain, final.tar_extract.leaf_link_chain |

## Resource use

SDK-reported coding cost totals **$1.4059**, excluding advisor charges.
The nine cached advisor slots used 188,483 recorded input tokens and 8,170 output tokens across their recorded attempts.
Advisor time totalled 99.6 seconds. Missing advisor usage slots: 0.
Each policy-bearing arm would incur those advisor tokens independently without sharing; actual cached requests were charged only once per pair. Advisor dollar cost is unknown.

| Condition | Agent time | Median/run | Verifier time | Missing SDK cost calls |
| --- | ---: | ---: | ---: | ---: |
| baseline | 324.8s | 30.8s | 6.9s | 0 |
| policy | 408.2s | 30.6s | 7.0s | 0 |
| verification | 396.8s | 29.4s | 7.5s | 0 |
| full | 489.6s | 47.0s | 7.0s | 0 |

## Scope and evidence

- Three familiar Python development tasks; three repetitions each; no significance or general security claim
- Final tests withhold input combinations, not entire vulnerability classes or repositories
- Equal iteration/runtime ceilings do not equal realized cost; repair also changes conversation staging
- Advisor results are cached/shared within each task/repetition; pair outcomes are correlated
- SDK costs are estimates; missing usage is unknown rather than zero; advisor dollars are not estimated

Local artifacts: `.artifacts/simple-design-execution`. Machine-readable analysis, source/check hashes, per-run traces and candidate files remain there.
Execution manifest SHA-256: `32896e5467fed8fa6bf5106847655156429bf3c3869e761504d8a489a9398a97`.

## Interpretation and case review

The simpler harness produced a positive development-pilot signal: each harness
condition achieved two more joint successes than baseline, with no observed
functional regressions. All differences came from archive extraction. SQL search
and document reads passed in every condition, leaving no observed room for
improvement on those tasks. These observations support further evaluation; they
do not establish a general effect or statistical significance.

### Why the baseline failed

Both `tar_extract-r2-baseline` and `tar_extract-r3-baseline` rejected absolute
member names and `..` segments and extracted regular files only. They then opened
destination paths without checking existing filesystem links. A syntactically
safe member name could therefore write outside the destination through an
existing directory or leaf symlink. Both withheld link-chain checks failed.

The repetition-2 baseline trace records successful agent-authored unit tests
after an internal fix for absolute paths. Internal verification was active, but
its tested cases did not cover the remaining filesystem-link boundary.

### What policy guidance contributed

The cached archive advice explicitly covered canonical destination containment
and symlink escapes. Repetition 2 selected canonicalization policy
`OWASP-SCP-a7346c058dcf`; repetition 3 also selected additional-controls policy
`OWASP-SCP-9742afe07244`, with guidance addressing pre-existing links.

The corresponding policy-only candidates added concrete protections:
repetition 2 resolved each destination and checked containment; repetition 3
checked resolved parent containment and used `O_NOFOLLOW` when opening files.
Both passed all final checks. This is implementation evidence consistent with
the advice, but independent stochastic generations cannot prove that a specific
SCP caused the difference. The treatment includes both selected SCP text and
LLM-written task-specific guidance; this experiment does not isolate their effects.
Passing these checks also does not establish safety under concurrent filesystem
mutation or on untested platforms.

### What external verification contributed

`tar_extract-r2-verification` initially passed its two development functional
checks but failed the existing-directory-symlink and existing-leaf-symlink checks.
The controller supplied those failures to OpenHands in one bounded repair call.
The revised implementation walked directories through file descriptors and used
`O_NOFOLLOW` for directory and file opens. It then passed all eight development
checks and all eight final checks, preserving functionality. The initial call
took 39.9 seconds and repair took 57.6 seconds.

This demonstrates a useful external-verification/repair path beyond the agent's
initial work. It does not attribute the entire verification-versus-baseline
difference to repair: only one verification run was repaired, and the arms used
separate generations with different initial iteration allocations.

The combined condition required no external repairs and did not outperform
either component alone. Its higher observed coding cost therefore bought no
additional measured success in this pilot. Advisor input usage is also substantial
relative to these small tasks and must be included in future affordability
comparisons; the reported $1.4059 excludes advisor charges.

## Next experiment

Keep the simple implementation and AST disabled. Before introducing more harness
components, qualify a broader set of repository tasks with vulnerable, safe,
reject-all and no-op controls, then freeze another evaluation protocol. Use
development tasks to validate the pipeline and distinct held-out repositories
for the primary effectiveness claim. Choose repetitions and budget before
observing those outcomes.

Retain the four conditions and joint functional/security outcome. Add a matched
generic-security-advice control to distinguish the benefit of policy selection
from additional security instructions, and record initial versus repaired
outcomes separately. Track complete coding and advisor costs. Keep the proposed
advanced verification design on its separate branch until this simpler design's
effect and limitations are better measured.

## Reproduction and audit

The statistical sections above were generated by
`scripts/analyze_simple_comparison.py`; this interpretation was reviewed against
the saved candidate code, cached guidance, repair diff, and command traces.
The analyzer checked all 36 scheduled identities, their frozen candidate hashes,
treatment and repair prompts, iteration allocations, and raw verifier summaries.
An independent count from `results.json` agreed with the four outcome totals.
All 36 final evaluations were healthy; the nine advisor slots had no errors.
The execution source remained frozen throughout generation and scoring.

Run the command in the [harness README](../harness/README.md#isolated-python-comparison)
to regenerate the tables into a separate file. Raw artifacts are local and ignored
by Git; the public repository contains the protocol, implementation, analysis
script, and this report, but not the complete run evidence.
