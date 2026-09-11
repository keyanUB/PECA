# PECA trusted verifier

This milestone provides frozen task/candidate/result contracts, a reviewed check
registry, explicit obligation mappings, and a Docker verifier. The
[OpenHands controller](../docs/controller-design.md) now supplies an agent adapter,
bounded external repair, and acceptance against these checks.

Run from PECA with Python 3.12+ and a working local Docker daemon. Runtime code uses
only the Python standard library. Fetch the runtime image explicitly once:

```bash
docker pull python:3.12-slim
python3 -m harness.verification list
python3 -m harness.verification run \
  --task harness/examples/tar-task.json \
  --candidate harness/tests/fixtures/tar_extract_secure.py \
  --bindings harness/examples/tar-bindings.json \
  --output .artifacts/verifier-example
```

The output directory must not exist. CLI exit codes: `0` means all executed
checks and requested mappings passed, `1` means a failed check or unmapped
obligation, `2` means invalid configuration, infrastructure error, or timeout.
A successful verifier exit is not a controller acceptance decision.

## Supported contracts and checks

| Family | Candidate API | Functional checks | Security checks |
| --- | --- | --- | --- |
| `sql_search` | `search_users(connection, query)` | 5 | 3 |
| `document_read` | `read_document(root, name)` | 3 | 3 |
| `tar_extract` | `unpack_archive(archive_path, output_dir)` | 2 | 6 |

SQL expects literal case-insensitive substring lookup of `users(id, username)`,
returning matching tuples ordered by ID without modifying rows. Document reads
return UTF-8 content within a trusted root. Archive extraction preserves nested
regular files and returns sorted relative POSIX paths.

Archive probes cover parent traversal, absolute paths, archive-created symlinks
and hardlinks, existing directory symlinks, and existing file symlinks. The new
suite is derived from the pilot evaluator, with the leaf-file symlink case added.
Historical experiment evaluators and scores are not changed.

## Mapping advisor proposals

An operator-authored binding connects an advisor obligation ID to reviewed check
IDs. Free-text descriptions and suggested commands are never executed. There is
no automatic assertion that a policy or obligation is covered merely because its
words resemble a check name. Mappings must be reviewed for semantic suitability.

```json
[
  {
    "obligation_id": "archive-path-containment",
    "check_ids": [
      "tar_extract.parent_traversal",
      "tar_extract.absolute_path",
      "tar_extract.preexisting_symlink",
      "tar_extract.preexisting_leaf_symlink"
    ]
  },
  {"obligation_id": "concurrent-filesystem-mutation", "check_ids": []}
]
```

The empty binding is reported `unverified`, never passed. Unknown, duplicate, or
wrong-family check mappings are rejected. The harness cannot infer missing
obligations omitted from the mapping file. All 22 registry checks are versioned;
every run executes all baseline checks for its family, regardless of mappings.
An obligation's `passed` status means only its mapped checks passed within scope.

## Evidence and isolation

Candidate source is read once into immutable bytes, limited to 200,000 bytes,
and hashed. Each evidence directory contains the candidate snapshot, bounded
execution output, and `report.json`. Results include candidate hashes, check
versions, a fingerprint of the verifier implementation, and environment metadata.
The repository revision is caller-supplied provenance, not a verified repository
snapshot at this single-file milestone.

Docker resolves the selected image to its immutable ID before running. The
container has no network, a read-only root filesystem, read-only candidate and
probe mounts, a non-root user, no capabilities, no-new-privileges, and bounded
memory, CPU allocation, PIDs, files, output, and wall time. Its writable temporary
filesystem is discarded. Host API keys and agent workspace directories are not
mounted or forwarded. There is no unsandboxed fallback and no automatic image pull.
Only a trusted local Docker daemon and trusted Python 3.12 image are supported.

Malformed/incomplete output and infrastructure failures are `error`; wall-time
expiration is `timeout`. They are not evidence of security success or a confirmed
vulnerability. Container cleanup is attempted on all execution paths and any
cleanup uncertainty is reported. Evidence directories are not tamper-proof archives;
keep them outside agent-writable mounts when integrating a controller.

**Important scope:** candidate functions and probes share a Python interpreter
inside Docker. Deliberately malicious Python can introspect or modify the evaluator
in memory or forge its output. Read-only mounts protect files, not interpreter
state. This milestone evaluates ordinary buggy generated code; it does not claim
result integrity against adversarial candidate programs. Stronger separation is
required before treating that as part of PECA's threat model.

The suite does not prove complete security, check filesystem races, or certify all
SCPs. No LLM scoring is used. Hidden benchmark tests are not part of the registry
and must stay outside future repair feedback.

## Development checks

```bash
.venv/bin/python -m pytest harness/tests -q
PECA_TEST_DOCKER=1 .venv/bin/python -m pytest harness/tests -q
```

The first command skips Docker integration tests; the second runs the complete
suite. Fixtures are intentionally secure/vulnerable controls, not production code.
The parent-only Tar fixture reproduces the historical coverage gap: directory
symlink validation passes, while the new file-symlink probe detects an outside write.

## Isolated Python comparison

`harness.experiments.simple` implements the four-condition development experiment
specified in the [frozen design](../docs/simple-design-experiment.md). A separate
execution manifest records the runtime and current qualification. AST remains disabled.

The existing 22 development checks supply repair feedback. A separate final suite
has 13 functional and 13 security checks across the same three task families.
It uses additional input combinations, literal SQL-like names, directory and file
symlink chains, mixed archives, and binary/empty file content. It shares threat
classes with development tests; this is withheld-case evaluation on familiar tasks,
not evidence of generalization to new repositories. Unicode test strings use
escaped source notation. No human prompt language is restricted.

The coding adapter accepts any nonempty programming-language label. That label
configures agent context; it does not imply a verifier exists for every language.
This particular experiment fixes Python tasks and checks. The SDK's native system
prompt and testing loop remain in use, with PECA instructions supplied through
`AgentContext.system_message_suffix`. The old `system_prompt` constructor keyword
was ignored by the installed SDK. SDK step calls and available usage/cost metrics
are now recorded; killed workers can still leave incomplete usage accounting.

```bash
# 13 controls × two suites × three rounds, with no model calls.
.venv/bin/python -m harness.experiments.simple qualify \
  --output .artifacts/simple-qualification

# One live MCP selection and one seeded OpenHands repair, outside the matrix.
.venv/bin/python -m harness.experiments.smoke \
  --output .artifacts/simple-smoke

# Check current evidence and freeze source, settings, packages, images and schedule.
.venv/bin/python -m harness.experiments.simple freeze \
  --qualification .artifacts/simple-qualification --smoke .artifacts/simple-smoke \
  --output .artifacts/simple-experiment

# Runs the 36-call matrix; final scores never become repair feedback.
.venv/bin/python -m harness.experiments.simple run \
  --output .artifacts/simple-experiment
```

Use new output directories. Qualification preserves every control outcome. A freeze
rejects stale smoke evidence, changed checks and invalid control reports. Execution
checks the source bundle, packages, model settings and candidate hashes. The agent
receives only its isolated workspace; final probes and reference files stay on the
host until separate verifier containers run. All generation finishes and candidate
hashes are recorded before final scoring starts. Final checks cannot be passed to
the repair function. A passing final security subset alone is not joint success.

The matrix reuses the SDK adapter and verifier, not the old host-executing Python
comparison script. Historical one-off schema, refinement and duplicate fixture
helpers and historical reports were removed from the working tree. Previously
committed files remain in Git history. Only current repository protocols, qualification, control evidence, and run
records are retained locally. Final verification
still assumes cooperative generated code rather than an adversarial candidate
trying to tamper with its in-process evaluator.

Historical Python comparison reports and raw runs have been removed. The reusable
runner, fixtures, protocol and analyzer remain available. The current repository
experiment is documented in the [task 59438 report](../docs/secrepobench-59438-results.md).

After producing a fresh Python comparison, validate its saved evidence and export
statistical tables without new model calls:

```bash
.venv/bin/python -m scripts.analyze_simple_comparison \
  .artifacts/YOUR-EXECUTION --report /tmp/peca-comparison-tables.md
```

This checks the frozen manifest, prompts, candidate hashes, and verifier reports.
The audit requires the frozen runtime's effective model metadata. If the SDK
cannot fetch its price map and falls back to different bundled metadata, the
model-settings fingerprint check can fail; restore network access and retry.
