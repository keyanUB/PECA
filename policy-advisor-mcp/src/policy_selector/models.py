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
