import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .catalog import Catalog
from .models import CodeFile, PreviousPolicy, SecurityContext, ProgramEvidence
from .repository import collect_repository
from .selector import Selector


def build_server(host="127.0.0.1", port=8765):
    catalog = Catalog(os.getenv("POLICY_SELECTOR_EXTRA_CATALOG"))
    selector = Selector(catalog)
    allowed_root = Path(os.getenv("POLICY_SELECTOR_REPO_ROOT", os.getcwd())).resolve()
    mcp = FastMCP("policy-advisor", host=host, port=port,
                  instructions="Select OWASP SCPs before coding; refine selection after code generation.")

    @mcp.tool()
    def policy_catalog() -> dict[str, Any]:
        """List source metadata, categories, and policies. Does not call an LLM."""
        return {**catalog.describe(), "policies": catalog.records()}

    @mcp.tool()
    async def select_for_task(task: str, security_context: SecurityContext | None = None,
                              propose_obligations: bool = False) -> dict[str, Any]:
        """Select relevant SCPs. Optional security_context or propose_obligations
        adds advisory verification obligations; no checks are executed.
        """
        return await selector.select("task", task, security_context=security_context,
                                     propose_obligations=propose_obligations)

    @mcp.tool()
    async def select_for_repository(task: str, repository_path: str | None = None,
                                    file_paths: list[str] | None = None,
                                    files: list[CodeFile] | None = None,
                                    security_context: SecurityContext | None = None,
                                    propose_obligations: bool = False,
                                    program_evidence: ProgramEvidence | None = None) -> dict[str, Any]:
        """Analyze a task and incomplete repository.

        Choose exactly one: repository_path on the server filesystem, or files
        containing relative path/content snapshots supplied by the client.
        Local paths must be within POLICY_SELECTOR_REPO_ROOT. file_paths filters
        local reads only. Snapshots support containers and remote clients without
        shared paths. Both modes are bounded and report partial coverage.
        Optional program_evidence supplies source-bound structural observations;
        it is advisory and never substitutes for independent security checks.
        """
        if (repository_path is None) == (files is None):
            raise ValueError("Provide exactly one of repository_path or files")
        if files is not None:
            if file_paths is not None:
                raise ValueError("file_paths is only valid with repository_path")
            code = files
            coverage = {"mode": "client_snapshot", "files_read": [f.path for f in code],
                        "bytes_read": sum(len(f.content.encode()) for f in code),
                        "partial": True, "note": "Only client-supplied files were analyzed; repository completeness is unknown."}
        else:
            code, coverage = collect_repository(repository_path, allowed_root, file_paths)
            coverage["mode"] = "server_filesystem"
        if not code:
            raise ValueError("No readable source files found in the repository selection")
        return await selector.select("repository", task, code, coverage=coverage,
                                     security_context=security_context, propose_obligations=propose_obligations,
                                     program_evidence=program_evidence)

    @mcp.tool()
    async def refine_selection(task: str, generated_code: list[CodeFile],
                               previous_selection: list[PreviousPolicy],
                               security_context: SecurityContext | None = None,
                               propose_obligations: bool = False,
                               program_evidence: ProgramEvidence | None = None) -> dict[str, Any]:
        """Reassess previous SCPs against generated code and the original task.

        Pass each previous policy_id with its rationale/guidance. Results retain,
        add, or remove policies and assess implementation as satisfied/gap/uncertain.
        Optional program_evidence must match the generated code, not an older snapshot.
        """
        if not generated_code or not any(f.content.strip() for f in generated_code):
            raise ValueError("Provide nonempty generated code for refinement")
        return await selector.select("refinement", task, generated_code, previous_selection,
                                     security_context=security_context, propose_obligations=propose_obligations,
                                     program_evidence=program_evidence)

    return mcp


def main():
    parser = argparse.ArgumentParser(description="OWASP policy-advisor MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    build_server(port=args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
