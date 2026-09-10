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
