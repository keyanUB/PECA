"""Immutable, JSON-serializable contracts for the first harness milestone."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal


Family = Literal["sql_search", "document_read", "tar_extract"]
Status = Literal["passed", "failed", "error", "timeout", "unverified"]
FAMILIES = {"sql_search", "document_read", "tar_extract"}


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    family: Family
    request: str
    repository_revision: str
    timeout_seconds: int = 30

    def __post_init__(self):
        if self.family not in FAMILIES:
            raise ValueError("Unsupported task family")
        if not all(s.strip() for s in (self.task_id, self.request, self.repository_revision)):
            raise ValueError("Task identity, request, and repository revision are required")
        if not 1 <= self.timeout_seconds <= 300:
            raise ValueError("Timeout must be between 1 and 300 seconds")


@dataclass(frozen=True)
class Candidate:
    task_id: str
    source: bytes

    def __post_init__(self):
        if not self.task_id.strip() or not isinstance(self.source, bytes) or len(self.source) > 200_000:
            raise ValueError("Candidate requires a task ID and at most 200,000 immutable source bytes")

    @classmethod
    def from_file(cls, task_id: str, path: Path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Candidate must be a regular, non-symlink Python file")
        with path.open("rb") as stream:
            return cls(task_id, stream.read(200_001))

    @property
    def sha256(self):
        return sha256(self.source).hexdigest()


@dataclass(frozen=True)
class ObligationBinding:
    """A mapping approved by the harness operator, not an advisor command."""
    obligation_id: str
    check_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.obligation_id.strip() or not isinstance(self.check_ids, tuple):
            raise ValueError("Binding needs an obligation ID and immutable check IDs")
        if len(set(self.check_ids)) != len(self.check_ids):
            raise ValueError("Duplicate check IDs in obligation binding")


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    check_version: str
    candidate_sha256: str
    status: Status
    kind: Literal["functional", "security"]
    detail: str
    evidence_path: str


@dataclass(frozen=True)
class ObligationResult:
    obligation_id: str
    check_ids: tuple[str, ...]
    status: Status
    limitation: str = "Only the mapped probes were assessed; this does not prove the full policy."


@dataclass(frozen=True)
class VerificationReport:
    task: TaskSpec
    candidate_sha256: str
    registry_sha256: str
    environment: dict
    checks: tuple[CheckResult, ...]
    obligations: tuple[ObligationResult, ...]
    limitations: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AcceptanceDecision:
    """Controller-owned contract; the verifier does not construct acceptance decisions."""
    candidate_sha256: str
    decision: Literal["accept", "repair", "incomplete", "budget_exhausted"]
    reason: str
    evidence_paths: tuple[str, ...]
