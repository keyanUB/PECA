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
See the [pilot report](docs/repository-pilot-report.md) for results and qualification limits.

The MCP package is now `policy-advisor-mcp`, with server name `policy-advisor`.
Existing users should follow the [rename migration guide](policy-advisor-mcp/MIGRATION.md).

- [policy-advisor installation and tools](policy-advisor-mcp/README.md)
- [Cross-client integration status](policy-advisor-mcp/integrations/README.md)
- [Latest baseline/SCP comparison](policy-advisor-mcp/SECURITY_COMPARISON_FIXED.md)
- [OpenHands failed-case retest](policy-advisor-mcp/OPENHANDS_RETEST.md)

The latest comparison completed 12 generations. Primary security checks passed
21/22 for baseline and 22/22 for SCP guidance, but a supplementary probe found
a vulnerability in one implementation in each arm. These results do not establish
a general security improvement. Codex, Claude Code, and SWE-agent integrations
have not yet been verified end to end.

Raw experiment traces, local profiles, generated workspaces, and virtual environments
are excluded from Git. Report links into `.artifacts/` refer to local evidence and
will not resolve in a fresh clone. The reports and evaluation scripts are included;
follow the latest report to produce a new set of artifacts.

The OWASP data retains its upstream attribution and license; see
[the data notice](policy-advisor-mcp/src/policy_selector/data/NOTICE.md).
