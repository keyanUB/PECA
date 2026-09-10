"""Build the catalog from a downloaded official OWASP checklist Markdown file."""

import argparse
import hashlib
import json
import re
from pathlib import Path


URL = "https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/stable-en/02-checklist/05-checklist"
RAW_URL = "https://raw.githubusercontent.com/OWASP/www-project-secure-coding-practices-quick-reference-guide/master/stable-en/02-checklist/05-checklist.md"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "src/policy_selector/data")
    args = parser.parse_args()
    raw = args.markdown.read_bytes()
    policies = []
    category = None
    for line in raw.decode().splitlines():
        if line.startswith("## "):
            category = line[3:].strip()
        elif line.startswith("- [ ]") and category:
            policies.append({"category": category, "text": line[5:].strip()})
        elif line.startswith("    ") and policies:
            policies[-1]["text"] += " " + line.strip()
    if len({p["category"] for p in policies}) != 14 or len(policies) < 200:
        raise ValueError("Unexpected OWASP checklist structure; inspect source before updating")
    for p in policies:
        p["text"] = re.sub(r"\\([\"'])", r"\1", p["text"])
        digest = hashlib.sha256((p["category"] + "\n" + p["text"]).encode()).hexdigest()[:12]
        p["id"] = "OWASP-SCP-" + digest
        p["source_url"] = URL + "#" + p["category"].lower().replace(" ", "-")
    document = {"source": {"name": "OWASP Secure Coding Practices Quick Reference Guide",
                           "snapshot": "stable-en", "source_url": URL, "raw_url": RAW_URL,
                           "source_sha256": hashlib.sha256(raw).hexdigest(),
                           "id_scheme": "PECA content-derived IDs, not official OWASP identifiers"},
                "policies": policies}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "owasp-scp.json").write_text(json.dumps(document, indent=2) + "\n")
    (args.output / "owasp-checklist.md").write_bytes(raw)
    print(f"Imported {len(policies)} policies across 14 categories")


if __name__ == "__main__":
    main()
