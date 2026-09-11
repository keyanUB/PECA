# Interactive OpenHands launcher

This launcher is for interactive coding work, not the reproducible four-condition
experiment. For formal experiments, use the [run → evaluate → summarize workflow](../README.md#run-an-experiment).

## Setup and launch

From PECA in a Linux/macOS terminal or Ubuntu under Windows WSL:

```bash
python3 openhands_cli.py setup
python3 openhands_cli.py run
```

`setup` reuses OpenHands on your PATH if available. Otherwise it installs the
version in `requirements-openhands.txt` into `.venv-openhands` (requires Python
3.12+, venv/pip and internet access). A project-local installation takes priority.
The launcher itself uses only Python's standard library.

On first interactive launch, choose the provider/model and enter your API key in
OpenHands. Its configuration is stored under `~/.openhands`. The agent operates
in PECA by default and can execute commands and edit files; choose another
workspace when appropriate.

```bash
# Installation diagnosis: no agent or model request.
python3 openhands_cli.py doctor

# Wrapper options go before run.
python3 openhands_cli.py --workspace /path/to/project run

# Forward options to OpenHands.
python3 openhands_cli.py run -- --help
```

For Windows CMD, enter `wsl -d Ubuntu` first, then run these commands with the
project's WSL path. Native Windows CMD is not supported by this launcher.

## Connect the Policy Advisor

The independent [policy-advisor MCP](../policy-advisor-mcp/README.md) selects OWASP
Secure Coding Practices from public task/source evidence. Follow its installation
instructions and provide the required model credentials in the host environment:

```bash
python3 run_openhands_with_policy.py --workspace /path/to/project
```

Use this wrapper for Advisor integration; bare `openhands` does not load PECA's
MCP compatibility fix. See [selection workflows and verification](../policy-advisor-mcp/README.md),
[client integration status](../policy-advisor-mcp/integrations/README.md) and the
[package rename migration](../policy-advisor-mcp/MIGRATION.md).

Interactive operation does not establish the isolation or fairness properties of
a frozen experiment. Conversely, the repository experiment's custom OpenHands SDK
shell adapter is not the stock interactive CLI. Other client integrations must
not be presented as verified end to end without supporting evidence.
