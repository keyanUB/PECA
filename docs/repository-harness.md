# Repository harness and development pilot

PECA now has a repository execution path alongside its single-file controller. It
uses the OpenHands SDK's native reasoning loop with one PECA shell tool. The tool
runs commands in a disposable Docker container; it never executes the command on
the host. This path is a custom SDK integration, not the stock CLI or a replacement
for the agent's own tests and debugging loop.

## Boundaries

The SDK and MCP client run on the host with the model credential. The coding
container receives only a clean source workspace. It has no network, Docker socket,
benchmark answers, hidden PoC, host home, or API credential. Its root filesystem is
read-only, its user is the host's non-root UID, and its writable temporary directory,
CPU, memory, processes, command output and lifetime are bounded. Do not run this
path as root. The host supervisor removes the container on completion or timeout
and checks removal before collecting candidate files.

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

The four conditions share a maximum of 30 SDK iterations and 300 seconds of agent
runtime. Repair conditions allocate up to 20 iterations/200 seconds initially, then
at most 10 iterations with the remaining time for one external repair. Each repair
starts a fresh conversation against the retained workspace. These are resource
ceilings, not equal realized token expenditure. MCP selection and evaluator time
are additional costs; preserve guidance and SDK usage records when comparing cost.

## Research status

The frozen protocol covers a **development feasibility pilot**, not a confirmatory
security experiment. Development projects are excluded from the recorded validation
and held-out project lists. The split is preparatory: additional adapters, stable
reference oracles, reviewed policy-to-check bindings, policy-selection evaluation,
a sample-size calculation, and a separately preregistered confirmatory protocol are
required before held-out evaluation. Do not interpret this one-repetition pilot as
evidence of general security improvement.
