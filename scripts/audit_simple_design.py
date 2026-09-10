"""Audit existing probe overlap and fixture behavior without any model calls.

Run from PECA with: python -m scripts.audit_simple_design --output NEW_DIRECTORY
Candidate fixtures execute only through the existing Docker verifier.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from harness.contracts import Candidate, TaskSpec
from harness.verification.registry import CHECKS, fingerprint
from harness.verification.runner import DockerVerifier


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RemoveHarnessAdditions(ast.NodeTransformer):
    """Remove the documented leaf-symlink case and runtime version field only."""

    def visit_If(self, node):
        if ast.dump(node.test) == ast.dump(ast.parse("mode == 'preexisting_leaf_symlink'", mode="eval").body):
            return [self.visit(child) for child in node.orelse]
        return self.generic_visit(node)

    def visit_Tuple(self, node):
        node.elts = [item for item in node.elts
                     if not (isinstance(item, ast.Constant) and item.value == "preexisting_leaf_symlink")]
        return self.generic_visit(node)

    def visit_Dict(self, node):
        pairs = [(key, value) for key, value in zip(node.keys, node.values)
                 if not (isinstance(key, ast.Constant) and key.value == "python_version")]
        node.keys = [key for key, _ in pairs]
        node.values = [value for _, value in pairs]
        return self.generic_visit(node)


def functions(path, normalize=False):
    tree = ast.parse(path.read_text())
    if normalize:
        tree = RemoveHarnessAdditions().visit(tree)
    return {node.name: ast.dump(node, include_attributes=False)
            for node in tree.body if isinstance(node, ast.FunctionDef)}


def audit(output):
    output.mkdir(parents=True, exist_ok=False)
    legacy = ROOT / "policy-advisor-mcp/evaluation/evaluate.py"
    current = ROOT / "harness/verification/probes.py"
    old, normalized = functions(legacy), functions(current, normalize=True)
    identical = {name: old[name] == normalized[name] for name in ("sql_fixture", "evaluate")}
    if not all(identical.values()):
        raise ValueError("Evaluator overlap changed; review the audit instead of reusing its conclusion")
    fixture_root = ROOT / "harness/tests/fixtures"
    evidence_files = [legacy, current, Path(__file__).resolve(),
                      ROOT / "harness/verification/registry.py",
                      ROOT / "harness/verification/runner.py", ROOT / "harness/contracts.py",
                      ROOT / "policy-advisor-mcp/evaluation/cases.py",
                      ROOT / "policy-advisor-mcp/evaluation/probe_leaf_symlink.py",
                      *sorted(fixture_root.glob("*.py"))]
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in evidence_files}
    registry_hash = fingerprint()
    legacy_ids = [check.id for check in CHECKS if check.name != "preexisting_leaf_symlink"]
    cases = [(family, kind, (fixture_root / f"{family}_{kind}.py").read_bytes())
             for family in ("sql_search", "document_read", "tar_extract")
             for kind in ("secure", "vulnerable")]
    cases.append(("tar_extract", "parent_only", (fixture_root / "tar_parent_only.py").read_bytes()))
    for family, function in (("sql_search", "search_users"), ("document_read", "read_document"),
                             ("tar_extract", "unpack_archive")):
        cases.append((family, "reject_all", f"def {function}(*args):\n    raise ValueError('reject all')\n".encode()))
    rows = []
    for family, label, source in cases:
        case_id = f"{family}-{label}"
        task = TaskSpec(case_id, family, "Audit existing development checks against a known control", "audit-v1")
        report = DockerVerifier().verify(task, Candidate(case_id, source), output / case_id)
        functional = [c for c in report.checks if c.kind == "functional"]
        security = [c for c in report.checks if c.kind == "security"]
        healthy = not report.environment.get("cleanup_error") and all(c.status in ("passed", "failed") for c in report.checks)
        fpass = sum(c.status == "passed" for c in functional)
        spass = sum(c.status == "passed" for c in security)
        expected = (fpass == len(functional) and spass == len(security)) if label == "secure" else (
            fpass == 0 and spass == len(security) if label == "reject_all" else spass < len(security))
        if label == "parent_only":
            expected = fpass == len(functional) and [c.check_id for c in security if c.status == "failed"] == [
                "tar_extract.preexisting_leaf_symlink"]
        row = {"case": case_id, "candidate_sha256": report.candidate_sha256,
               "image_id": report.environment.get("image_id"), "registry_sha256": report.registry_sha256,
               "functional_passed": fpass, "functional_total": len(functional),
               "security_passed": spass, "security_total": len(security),
               "failed_checks": [c.check_id for c in report.checks if c.status == "failed"],
               "execution_healthy": bool(healthy), "matches_expected_control_behavior": bool(healthy and expected),
               "report": f"{case_id}/report.json"}
        rows.append(row)
        print(f"{case_id}: functional={fpass}/{len(functional)}, security={spass}/{len(security)}, healthy={bool(healthy)}", flush=True)
    unchanged = hashes == {path: sha(ROOT / path) for path in hashes} and registry_hash == fingerprint()
    same_image = len({r["image_id"] for r in rows}) == 1 and rows[0]["image_id"] is not None
    result = {"version": 1, "scope": "Development-suite audit; no coding generation, no advisor calls, no independent final evaluation",
              "source_sha256": hashes, "registry_sha256": registry_hash,
              "implementation_unchanged": unchanged, "single_verifier_image": same_image,
              "overlap": {"method": "AST equivalence after removing only the harness leaf-symlink case and Python-version output field",
                          "normalized_functions_equal": identical, "legacy_check_ids": legacy_ids,
                          "legacy_total": len(legacy_ids), "current_total": len(CHECKS),
                          "legacy_checks_reused_for_repair": len(legacy_ids),
                          "additional_repair_check": "tar_extract.preexisting_leaf_symlink",
                          "leaf_diagnostic": "Manually reviewed: the separate historical leaf-symlink probe tests the same outside-write mechanism as the additional repair check; no AST-equivalence claim for this file.",
                          "audited_independent_final_checks": 0},
              "fixtures": rows,
              "audit_passed": unchanged and same_image and all(r["matches_expected_control_behavior"] for r in rows),
              "execution_ready": False,
              "gaps": ["Independent final Python evaluator and qualification absent",
                       "Existing local single-file agent adapter does not isolate final test files",
                       "Existing isolated repository adapter has a C/C++ system prompt",
                       "Existing Python comparison runner has two arms and no external repair; the four-arm repository runner is SecRepoBench-specific"],
              "limitations": ["AST equivalence here audits Python evaluator source; optional Clang evidence remains disabled",
                              "Controls ran once each; not an effectiveness experiment or a comprehensive qualification",
                              "All-reject controls show why security-only probe passing cannot establish useful secure generation",
                              "Same-interpreter verifier does not resist malicious candidate tampering"]}
    (output / "audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if not result["audit_passed"]:
        raise RuntimeError("Audit control or provenance failed; preserve results and investigate")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args().output.resolve())
