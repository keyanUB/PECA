# Optional AST context for the policy advisor

PECA can extract bounded Clang observations and send them to the policy-advisor
MCP alongside the original source. The coding model remains `gpt-5.4-mini` and
the advisor remains `gpt-5.6-luna`. Existing MCP calls do not require AST evidence.
This feature supplies context; it does not verify security obligations.

## Development decision

AST remains an optional evidence source, disabled by default. Its effectiveness
evaluation is deferred until the core pipeline is ready. Further AST expansion
is not a prerequisite for completing that pipeline.

The immediate priority is reliable task/repository intake, policy selection,
agent generation, independent verification, bounded repair and reproducible
reporting. Pipeline readiness requires an end-to-end run on qualified benchmark
tasks, with incomplete agent work and evaluator failures distinguished from
functional and security results. Checks remain independent of whether the advisor
selects any policies.

Once that pipeline is ready, compare text-only context with text plus AST under
comparable budgets. Measure obligation quality, functional/security outcomes and
total cost, including extraction, build preparation and model usage. Until then,
the AST milestone establishes integration and traceability, not improved security
of generated code.

## Extractor

`harness.analysis` uses Clang's Python bindings inside a separate Docker image.
The host supplies an isolated source snapshot and a read-only control mount with
the trusted worker and request. The container has no network, API credentials or
Docker socket. Its root is read-only, its user is non-root when PECA runs as a
non-root user, and it has the same CPU/memory/process limits as the coding sandbox.
Parsing has a 45-second limit; output is bounded. Repository build preparation, when
requested by the benchmark integration, runs separately inside the analysis image
with a 120-second limit and no host command execution.

The extractor records function signatures, parameters, variables, calls,
arithmetic expressions, branches, returns, array accesses and member references.
It includes resolvable same-file callers. Direct declaration resolution does not
establish the callee's behavior; function-pointer calls remain unresolved.

Each fact contains a relative source path, byte offset, line number and exact
source quote. Evidence includes the source hashes, analyzed snapshot hash, worker
hash, compiler version, immutable image ID and explicit compiler arguments.
At most 80 facts are returned. For masked functions, the signature and facts nearest
the hole are prioritized. Truncation, missing headers, parse errors and missing
implementations are reported. `parsed` means Clang parsed the selected configuration;
it does not mean the program is safe or that every configuration was analyzed.

The current implementation uses explicit relative include directories, simple
macro definitions, and C GNU11 or C++17 parsing. It does not execute compilation
commands supplied by a repository, infer a compilation database, model library
semantics, or perform control-flow/taint/alias analysis. Templates and ambiguous
function names may require further support. There is no AST cache in this milestone;
re-analysis avoids stale-cache acceptance.

The general CLI snapshots C/C++ source/header extensions and excludes hidden paths
and `vendor`/`node_modules`. Only the target file contributes quoted facts. It is
not a complete repository call graph. Build-generated headers can be included,
and their bytes contribute to the analyzed snapshot identity. Header files in the
analysis image are identified by that image's immutable ID.

## Run

```bash
docker build -t peca-ast:clang-v1 -f harness/analysis/Dockerfile harness/analysis

.venv/bin/python -m harness.analysis \
  --repository /path/to/clean/source --target-file src/example.c \
  --function process_input --include include --define HAVE_CONFIG_H \
  --output .artifacts/example-ast
```

Omit `--function` to select the function enclosing `// <MASK>`. Add `--task '...'`
to call the real advisor MCP after extraction. This requires `OPENAI_API_KEY` on
the host; extraction alone has no model charges. `evidence.json`, `request.json`,
and extraction `metrics.json` are saved under the new output directory. A failed
analysis exits unsuccessfully and remains explicitly marked as unavailable.

The Dockerfile installs Clang from the image's configured package sources.
Rebuilds can differ over time: preserve the produced image ID and package/compiler
versions for experiments. The milestone used Clang 19.1.7.

## MCP contract

`select_for_repository` and `refine_selection` accept optional `program_evidence`.
The server validates the size, source hashes, unique fact IDs, byte offsets, line
numbers and exact quotes against the supplied code **before calling the model**.
Evidence from an old candidate is rejected. Failed analysis cannot supply facts.

The server labels returned evidence `validation: source_binding_only` and
`advisory: true`. This validates correspondence to submitted code, not the truth
of caller-supplied types, semantic claims, compiler identity or repository hash.
MCP clients cannot confer trust merely by claiming to be Clang. Source comments,
names and analysis text remain untrusted data in the model prompt.

With evidence supplied, the advisor returns proposed obligations using the existing
advisory schema. Obligations cite exact source quotes and retain `unverified`
status. AST fact IDs are distinct from optional security-context claim IDs.
Internally, the model selects fact IDs instead of retyping quotes; the server
resolves those references to the submitted facts' exact quotes. Unknown references
are rejected. The returned public selection schema continues to contain source/quote
evidence, preserving client compatibility. An empty selection remains valid advice.
For refinement, extract new evidence from the actual generated candidate.

## Optional pilot integration

```bash
.venv/bin/python -m harness.benchmarks.pilot freeze \
  --source .artifacts/sources/SecRepoBench --output .artifacts/ast-pilot \
  --evaluator qualified-v2 --ast-context

.venv/bin/python -m harness.benchmarks.pilot run \
  --source .artifacts/sources/SecRepoBench --output .artifacts/ast-pilot \
  --qualification .artifacts/reference-v2 --evaluator qualified-v2
```

The new protocol records whether AST context is enabled and pins the analysis
image ID. Baseline and verification-only coding prompts remain without policy
advice; the policy/full conditions receive AST-assisted selection. Existing
baseline checks still run independently of policy selection.

For the two supported development projects, reviewed configuration commands create
headers in a clean masked-source sandbox before extraction. They do not access gold
implementations or hidden PoCs. Parse and configuration coverage remain partial.
No new generation comparison is part of this milestone: selection improvement,
security improvement and token savings require a separate controlled experiment.

To exercise only repository extraction and advisor integration, without generation:

```bash
.venv/bin/python -m harness.analysis.benchmark_context \
  --source .artifacts/sources/SecRepoBench --output .artifacts/ast-advisor-check \
  --tasks 910 1065 --advise
```

References: [Clang AST matching](https://clang.llvm.org/docs/LibASTMatchers.html),
[compilation configuration](https://clang.llvm.org/docs/JSONCompilationDatabase.html).
