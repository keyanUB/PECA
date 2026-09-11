# Repository harness and development pilot

PECA now has a repository execution path alongside its single-file controller. It
uses the OpenHands SDK's native reasoning loop with one PECA shell tool. The tool
runs commands in a disposable Docker container; it never executes the command on
the host. This path is a custom SDK integration, not the stock CLI or a replacement
for the agent's own tests and debugging loop.

## Condition names

| Display name | Stable ID | Policy access | External repair |
| --- | --- | --- | --- |
| Baseline | `baseline` | None | None |
| Advisor-only | `policy` | Advisor-selected SCPs and task-specific guidance | None |
| Verification-only | `verification` | None | At most one attempt |
| Full | `full` | Advisor-selected SCPs and task-specific guidance | At most one attempt |

Advisor-only replaces the former display name Policy-only. Keep `policy` in
configuration, JSON, directory names and run IDs so existing artifacts remain
readable. New report renderers use the display names above; historical reports
and frozen protocols retain their original wording. All-SCP and SCP-RAG are
separate planned ablations, not alternative names for Advisor-only.

## Boundaries

The SDK and MCP client run on the host with the model credential. The coding
container receives a clean source workspace and, for policy-enabled conditions,
a separate read-only policy directory. It has no network, Docker socket,
benchmark answers, hidden PoC, host home, or API credential. Its root filesystem is
read-only, its user is the host's non-root UID, and its writable temporary directory,
CPU, memory, processes, command output and lifetime are bounded. Do not run this
path as root. The host supervisor removes the container on completion or timeout
and checks removal before collecting candidate files.

When an agent shell command exceeds the time/output boundary, its container is
retired before a replacement is started. The agent receives a recoverable tool
error and instructions to narrow its search. Workspace files and the policy mount
survive; temporary files and running processes do not. Evaluator commands retain
their strict failure behavior. Failure to clean up or recreate a container remains
a fatal error.

Only the repository shell is registered as an executable agent tool; SDK finish
and think actions remain available. MCP guidance is requested by PECA and supplied
as advisory data. It grants no execution privileges. Repository prompt injection
can still influence code and consume budget; isolation limits its available actions.
Docker is the trust boundary, not proof against kernel/container escapes.

The benchmark evaluator uses separate ephemeral ARVO containers without host
mounts or credentials. Their root is writable for compilation, and DAC_OVERRIDE
allows the upstream build wrapper to use image-owned build directories. This
capability is never added to coding containers. Source enters through Docker copy;
logs leave through bounded command output. Generated code still executes inside
these containers, and candidate code could tamper with same-container test state.
The current evaluator is suitable for cooperative coding-agent experiments, not
an adversarial benchmark-integrity guarantee.

## Snapshots and patches

`harness/repository.py` imports bounded regular files from a Git archive. It rejects
links, traversal, unsupported modes and oversized entries. Manifests hash bytes and
executable modes. Patch bundles record additions, deletions, mode changes and binary
changes with content-addressed blobs. Replay checks both base and result hashes;
`review.diff` is only a human-readable aid.

The SecRepoBench runner records changes to the imported tracked files and replays
only the target completion file into evaluation containers, matching upstream's
whole-file completion interface. Agent-created files and tests remain in the raw
workspace and tool trace but are not included in the scored patch. The generic
snapshot API can capture explicit added paths; automatic discovery of new files
and arbitrary multi-file benchmark evaluation are not implemented.

## SecRepoBench adapter

The adapter pins the [upstream source](https://github.com/ai-sec-lab/SecRepoBench)
to `7ca5c4a7e908f8013e7b9ae624ba0d96f8c6ec76` and currently supports development
tasks from `lcms` and `file`. A Git archive of the fixing revision is masked with
the upstream completion input. Git history and reference implementations are not
placed in the coding workspace. The agent receives only the public task description,
target path and incomplete repository. The advisor receives the task and target-file
snapshot, explicitly reported as partial repository coverage.

Developer tests are the upstream commands parsed as literal data from
`assets/projects.py`. Hidden security evaluation runs `arvo compile` then `arvo run`
only after the final candidate is frozen. Hidden results never trigger repairs.
A task qualifies for joint scoring only if the secure reference passes both checks
and the vulnerable reference fails the hidden PoC. Failed reference qualification
remains visible in results. It does not count as a generated-code vulnerability.

A developer suite that fails on its secure reference cannot trigger external
repairs. Even a healthy developer suite is functional evidence; no reviewed mapping
from OWASP obligations to C/C++ security checks exists yet. Agent-written tests do
not independently discharge those obligations.

## Reproduce

Use Linux or WSL, a non-root Docker-capable user, PECA's installed Python environment,
an OpenHands SDK environment, and `OPENAI_API_KEY` in the host environment. The
images must already be installed; the runner does not pull them automatically.
The development pilot used `ghcr.io/openhands/agent-server:61470a1-python`,
`n132/arvo:910-fix`, and `n132/arvo:1065-fix`; immutable IDs are recorded in artifacts.

```bash
git clone https://github.com/ai-sec-lab/SecRepoBench .artifacts/sources/SecRepoBench
git -C .artifacts/sources/SecRepoBench checkout 7ca5c4a7e908f8013e7b9ae624ba0d96f8c6ec76

.venv/bin/python -m harness.benchmarks.pilot qualify \
  --source .artifacts/sources/SecRepoBench --output .artifacts/reference-checks
.venv/bin/python -m harness.benchmarks.pilot freeze \
  --source .artifacts/sources/SecRepoBench --output .artifacts/repository-pilot
.venv/bin/python -m harness.benchmarks.pilot run \
  --source .artifacts/sources/SecRepoBench --output .artifacts/repository-pilot \
  --qualification .artifacts/reference-checks \
  --openhands-python /path/to/openhands-environment/bin/python

PECA_TEST_DOCKER=1 .venv/bin/python -m pytest harness/tests -q

# Separately exercise a seeded C repair with one real OpenHands repair call.
.venv/bin/python -m scripts.run_repository_repair_smoke \
  --output .artifacts/seeded-repository-repair

# Export a completed pilot's compact results; raw traces stay local.
.venv/bin/python -m scripts.summarize_repository_pilot \
  .artifacts/repository-pilot --output .artifacts/repository-pilot-summary
```

Use new output directories. Freeze records run order, project split, budgets,
models, image identity and implementation hashes before generation. Editing the
implementation or frozen protocol invalidates `run`. Interrupted pilots are not
automatically resumed; preserve partial evidence and freeze a new run directory.
Qualification results are checked against the benchmark reference hashes and image.

New protocol version 2 freezes allow **one external repair after initial
generation** by default. Baseline and Advisor-only receive one call of up to 60
iterations. Verification-only and Full receive up to 60 initial iterations and
one repair of up to 60 iterations, for 120 total. Time ceilings remain unchanged:
600 seconds for the nonrepair call; 300 seconds initially and 300 seconds for repair.
Allocated iterations and elapsed agent time are tracked across calls. Iteration
ceilings are now equal per call, not equal per condition; record this resource
asymmetry when interpreting future comparisons. MCP selection and evaluator time
are additional costs.

Set `--max-external-repairs 1` explicitly on `freeze` to record that limit. Another
limit changes the repair-arm iteration ceiling to 60 + 60 times the repair limit;
nonrepair conditions remain at 60 iterations. The existing time formula remains
300 + 300 times the repair limit in seconds. Zero disables external repair.
The 60+60 configuration has been exercised in a new Advisor-only/Full task 59438
rerun. Existing frozen results retain their original budgets.

A completed target with a failed qualified developer check can receive repair
even if the agent reached its iteration limit before signaling completion.
Operational errors, timeouts, missing completion code, and unqualified developer
checks cannot trigger repair. Passing developer checks alone does not trigger a
continuation. Final joint acceptance still requires normal agent completion as
well as both functional and hidden checks. Each repair starts a fresh conversation
against the retained workspace, with only the latest developer failure as feedback.

Both Advisor-only and Full mount a `compact-advice-v1` document at
`/peca-control/policy.json`. Selected SCP texts and scoped guidance appear first.
The document also preserves rationale, assessment, advisory obligations, applicability
conditions, suggested checks, uncertainty and context statements. Repeated quotations,
usage, catalog metadata and rejected model outputs remain in `guidance-audit.json`
outside the agent mount. Both file hashes are recorded; the policy file is read-only
and excluded from candidate patches and evaluations.

The prompt requests the entire file on every initial/repair call using the standalone
`cat /peca-control/policy.json` command. There is no fixed line/character read limit
or pagination. When the read-only policy mount is present, that exact command uses
uncapped output capture and its full text is passed into the SDK tool observation.
The ordinary shell's output protections remain applicable to other commands; command
timeouts and container isolation are unchanged. Model context capacity still applies.

Each round records `policy_delivery`: complete-file exposure, expected character
count and file hash. `policy_delivery_complete` requires the complete file in a
successful tool observation on every executed round. Prefixes and hashes alone do
not pass. The auditor uses the same output selection function as the SDK, including
the full-policy-read marker; it does not mistake a longer host log for model exposure.
The summary displays exposure separately from functional, PoC and joint outcomes.
Old results without this field are marked unrecorded.

This is a post-run exposure check, not a command-blocking gate or proof of model
attention, semantic relevance, instruction compliance, or read-before-edit ordering.
Incomplete exposure remains recorded; it cannot substantiate a claim about fully
consumed advice. Reading still incurs model input-token costs.

The earlier four-condition task 59438 comparison used full-JSON/prefix-read delivery.
The later Advisor-only/Full rerun used a fresh freeze and exercised the compact,
complete-read delivery. It does not revise the earlier frozen results.

## Research status

The [task 59438 comparison](secrepobench-59438-results.md) records all four outcomes,
reused control provenance and evaluator qualification. Use `--tasks 59438 --evaluator
qualified-v3` consistently for qualification and freezing. The v3 developer suite
adds functional cases that reject trivial parsers; its hidden PoC remains unchanged.
Baseline and Verification-only were reused after verifying unchanged execution and
evaluation. Advisor-only and Full were run with repaired evidence-reference selection.
All four final candidates passed the hidden PoC and failed functionality. Both repair
arms corrected their upstream failure but failed the extension's positive cases.
The earlier policy arms read only the first 120 lines of the policy file. A later
60 / 60+60 rerun used the compact delivery format and recorded complete policy
exposure on every Advisor-only and Full call. Both conditions still failed functional
acceptance and passed the hidden PoC. The report separates these protocols and does
not combine the older Verification-only 30+30 run with the newer Full 60+60 run as
a matched estimate.

The frozen protocol covers a **development feasibility pilot**, not a confirmatory
security experiment. Development projects are excluded from the recorded validation
and held-out project lists. The split is preparatory: additional adapters, stable
reference oracles, reviewed policy-to-check bindings, policy-selection evaluation,
a sample-size calculation, and a separately preregistered confirmatory protocol are
required before held-out evaluation. Do not interpret this one-repetition pilot as
evidence of general security improvement.
