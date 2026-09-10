from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Policy(StrictModel):
    id: str
    category: str
    text: str
    source_url: str


class Evidence(StrictModel):
    source: str = Field(description="task or a supplied relative file path")
    quote: str = Field(min_length=1, description="Exact substring from that source")


class Decision(StrictModel):
    policy_id: str
    rationale: str = Field(min_length=1)
    guidance: str = Field(min_length=1, description="Concrete, scoped implementation advice")
    evidence: list[Evidence] = Field(min_length=1)
    assessment: Literal["applicable", "satisfied", "gap", "uncertain"]


class Removal(StrictModel):
    policy_id: str
    rationale: str = Field(min_length=1)


class Selection(StrictModel):
    summary: str
    selected: list[Decision]
    removed: list[Removal]
    limitations: list[str]


class CodeFile(StrictModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=200_000)


class PreviousPolicy(StrictModel):
    policy_id: str
    rationale: str = ""
    guidance: str = ""


class ContextClaim(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    statement: str = Field(min_length=1, max_length=2000)
    status: Literal["supported", "assumed", "unknown"]
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)


class SecurityContext(StrictModel):
    assets: list[ContextClaim] = Field(default_factory=list, max_length=20)
    untrusted_inputs: list[ContextClaim] = Field(default_factory=list, max_length=20)
    sensitive_operations: list[ContextClaim] = Field(default_factory=list, max_length=20)
    trust_boundaries: list[ContextClaim] = Field(default_factory=list, max_length=20)
    assumptions: list[ContextClaim] = Field(default_factory=list, max_length=20)

    def claims(self):
        return [claim for name in type(self).model_fields for claim in getattr(self, name)]


class ProposedCheck(StrictModel):
    method: Literal["behavioral_test", "static_analysis", "configuration_review", "manual_review"]
    description: str = Field(min_length=1, max_length=2000)
    expected_evidence: str = Field(min_length=1, max_length=2000)


class Obligation(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    requirement: str = Field(min_length=1, max_length=2000)
    policy_ids: list[str] = Field(min_length=1, max_length=20)
    context_ids: list[str] = Field(max_length=20)
    applicability_conditions: list[str] = Field(max_length=20)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)
    suggested_checks: list[ProposedCheck] = Field(min_length=1, max_length=10)
    limitations: list[str] = Field(max_length=20)


class AdvisorySelection(Selection):
    obligations: list[Obligation] = Field(max_length=30)
