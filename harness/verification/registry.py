from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class CheckSpec:
    id: str
    family: str
    name: str
    kind: str
    version: str = "1.0.0"


FUNCTIONAL = {
    "sql_search": ("case_insensitive_lookup", "missing_user", "quoted_name", "literal_percent", "literal_underscore"),
    "document_read": ("plain_read", "nested_read", "unicode_read"),
    "tar_extract": ("nested_files", "empty_archive"),
}
SECURITY = {
    "sql_search": ("boolean_sql_injection", "union_sql_injection", "stacked_sql_injection"),
    "document_read": ("traversal", "absolute", "symlink"),
    "tar_extract": ("parent_traversal", "absolute_path", "symlink_member", "hardlink_member",
                    "preexisting_symlink", "preexisting_leaf_symlink"),
}
CHECKS = tuple(CheckSpec(f"{family}.{name}", family, name, kind)
               for kind, families in (("functional", FUNCTIONAL), ("security", SECURITY))
               for family, names in families.items() for name in names)


def for_family(family):
    checks = tuple(c for c in CHECKS if c.family == family)
    if not checks:
        raise ValueError("Unsupported task family")
    return checks


def fingerprint():
    """Bind the manifest, probe implementation, and runner to each report."""
    root = Path(__file__).parent
    bundle = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (root / "probes.py", root / "runner.py", root / "registry.py",
                        root.parent / "contracts.py")}
    return hashlib.sha256(json.dumps({"checks": [asdict(c) for c in CHECKS], "bundle": bundle},
                                    sort_keys=True).encode()).hexdigest()


def validate_bindings(family, bindings):
    allowed = {c.id for c in for_family(family)}
    if len({b.obligation_id for b in bindings}) != len(bindings):
        raise ValueError("Duplicate obligation bindings")
    for binding in bindings:
        if not set(binding.check_ids) <= allowed:
            raise ValueError("Binding refers to unknown or wrong-family checks")
