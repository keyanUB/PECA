import hashlib
import json
from importlib.resources import files
from pathlib import Path

from .models import Policy


class Catalog:
    """Load bundled OWASP policies, optionally extended with another JSON catalog."""

    def __init__(self, extra_path: str | None = None):
        paths = [files("policy_selector").joinpath("data/owasp-scp.json")]
        if extra_path:
            paths.append(Path(extra_path))
        self.policies: dict[str, Policy] = {}
        self.sources: list[dict] = []
        for path in paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            self.sources.append(document["source"])
            for record in document["policies"]:
                policy = Policy.model_validate(record)
                if policy.id in self.policies:
                    raise ValueError(f"Duplicate policy ID: {policy.id}")
                self.policies[policy.id] = policy
        if not self.policies:
            raise ValueError("Policy catalog is empty")
        self.digest = hashlib.sha256(
            json.dumps(self.records(), sort_keys=True).encode()
        ).hexdigest()

    def records(self) -> list[dict]:
        return [p.model_dump() for p in self.policies.values()]

    def describe(self) -> dict:
        return {"sha256": self.digest, "count": len(self.policies),
                "sources": self.sources,
                "categories": sorted({p.category for p in self.policies.values()})}
