"""Manifest for final behavioral probes, independent of development payloads."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from harness.verification.registry import CheckSpec

FUNCTIONAL = {
    "sql_search": ("literal_corpus", "multiple_matches", "empty_query", "no_match", "literal_sql_text", "connection_preserved"),
    "document_read": ("text_corpus", "empty_document", "normalized_inside_path", "missing_raises"),
    "tar_extract": ("binary_tree", "existing_destination", "empty_files"),
}
SECURITY = {
    "sql_search": ("boolean_variants", "union_variants", "statement_variants", "newline_comment"),
    "document_read": ("nested_escape", "directory_link_chain", "sibling_link", "absolute_secret"),
    "tar_extract": ("mixed_parent_escape", "mixed_absolute_escape", "directory_link_chain", "leaf_link_chain", "archive_link_chain"),
}
CHECKS = tuple(CheckSpec(f"final.{family}.{name}", family, name, kind)
               for kind, groups in (("functional", FUNCTIONAL), ("security", SECURITY))
               for family, names in groups.items() for name in names)


def for_family(family):
    found = tuple(c for c in CHECKS if c.family == family)
    if not found:
        raise ValueError("Unsupported final-check family")
    return found


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    paths = ("experiments/final_registry.py", "experiments/final_probes.py",
             "verification/runner.py", "verification/registry.py", "contracts.py")
    bundle = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(json.dumps({"checks": [asdict(c) for c in CHECKS], "bundle": bundle}, sort_keys=True).encode()).hexdigest()
