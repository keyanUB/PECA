# PECA

Python tooling for selecting secure coding policies and evaluating their use by coding agents.

The independent [policy-advisor MCP](policy-advisor-mcp/README.md) selects OWASP
Secure Coding Practices using `gpt-5.6-luna`. To run OpenHands connected to it:

```bash
python3 run_openhands_with_policy.py --workspace /path/to/project
```

See its README for installation, the three selection workflows, and verification.

## Quick start

Run from a Linux/macOS terminal or Ubuntu under Windows WSL:

```bash
cd PECA
python3 openhands_cli.py setup
python3 openhands_cli.py run
```

`setup` reuses OpenHands on your PATH if available. Otherwise it installs the
version in `requirements-openhands.txt` into `.venv-openhands` (requires Python
3.12+, venv/pip, and internet access). A project-local installation takes priority.
The launcher itself uses only Python's standard library.

On first interactive launch, choose your LLM provider/model and enter your API
key in OpenHands. OpenHands stores configuration under `~/.openhands`.
The agent operates in PECA by default and can execute commands and edit files.

```bash
# Check installation without starting an agent or making an LLM request
python3 openhands_cli.py doctor

# Select another existing workspace (wrapper options go before run)
python3 openhands_cli.py --workspace /path/to/project run

# Forward options to OpenHands
python3 openhands_cli.py run -- --help
```

For policy-advisor integration, use `run_openhands_with_policy.py`; bare
`openhands` does not load PECA's MCP compatibility fix.

For Windows CMD, enter `wsl -d Ubuntu` first, then use the Linux commands above
with your project's WSL path. Native Windows CMD execution is not supported by
this launcher.

Reference: [OpenHands CLI installation](https://docs.openhands.dev/openhands/usage/cli/installation).

## Project status and evaluation

The [harness contracts and trusted verifier](harness/README.md) provide Docker-based
functional/security checks for SQL queries, document reads, and archive extraction.
The [OpenHands controller](docs/controller-design.md) connects policy guidance,
generation, independent acceptance checks, and bounded external repair.
The [repository harness](docs/repository-harness.md) adds isolated OpenHands SDK
execution, replayable source patches, and a pinned SecRepoBench development pilot.
See [optional AST context](docs/ast-context.md) and the
[versioned evaluator](docs/evaluator-v2.md) for their scope and usage.
The [simpler-design experiment protocol](docs/simple-design-experiment.md) freezes
the four-condition development comparison with AST disabled, including
separate final evaluation and the required execution gates.
The [isolated Python comparison runner](harness/README.md#isolated-python-comparison)
now provides separate final checks, control qualification and execution freezing.

The MCP package is now `policy-advisor-mcp`, with server name `policy-advisor`.
Existing users should follow the [rename migration guide](policy-advisor-mcp/MIGRATION.md).

- [policy-advisor installation and tools](policy-advisor-mcp/README.md)
- [Cross-client integration status](policy-advisor-mcp/integrations/README.md)

The [SecRepoBench task 59438 report](docs/secrepobench-59438-results.md) records
the current development comparison and evaluator qualification. Repository runs
allow 60 SDK iterations for Baseline and Advisor-only. Verification-only and Full
allow 60 initial iterations plus at most one 60-iteration repair (120 total).
Time budgets remain 600 seconds per condition, split 300+300 for repair arms. Advisor-only receives policies in a read-only file.
Shell time/output limit failures return recoverable observations to the agent.
The advisor now uses server-indexed evidence references. The latest task 59438
Advisor-only and Full rerun used the 60 / 60+60 iteration settings. Both conditions
read the complete compact policy on every agent call and passed the hidden PoC, but
both failed functional acceptance. The report retains the earlier partial-exposure
comparison separately. This single-task result does not establish general security
improvement; policy relevance remains for human review.
Codex, Claude Code and SWE-agent integrations remain unverified end to end.

The [ablation study plan](ablation-study/PLAN.md) specifies All-SCP and SCP-RAG
as separate ablations of policy access. These conditions are planned, not implemented.

The policy-guided condition without external repair is named **Advisor-only**
(formerly Policy-only). Its stable code/result ID remains `policy` for compatibility
with frozen protocols and artifact paths. It uses Advisor-selected SCPs and
task-specific guidance; it is distinct from the planned All-SCP and SCP-RAG ablations.

Historical reports and raw experiment results have been removed from the working
tree. The benchmark source checkout, client configuration and current experiment's
qualification, control evidence and run records remain local under `.artifacts/`.
Those files and virtual environments are excluded from Git. Use the harness
instructions to create fresh evidence in a new clone.

The OWASP data retains its upstream attribution and license; see
[the data notice](policy-advisor-mcp/src/policy_selector/data/NOTICE.md).
