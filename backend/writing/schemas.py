from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Level = Literal["CET-4", "CET-6"]
RaterRole = Literal["strict", "lenient"]
WritingModel = Literal["deepseek-flash", "deepseek-v4-pro"]

WRITING_MODELS = [
    {
        "id": "deepseek-flash",
        "name": "DeepSeek V4.1 Flash",
        "description": "Fast default for parallel multi-agent review.",
    },
    {
        "id": "deepseek-v4-pro",
        "name": "DeepSeek V4 Pro",
        "description": "Higher-cost option for more deliberate review.",
    },
]


def score_band(score: int) -> int:
    if score <= 3:
        return 2
    if score <= 6:
        return 5
    if score <= 9:
        return 8
    if score <= 12:
        return 11
    return 14


class EssayInput(BaseModel):
    topic: str = Field(min_length=1, max_length=4000)
    essay: str = Field(min_length=1, max_length=20000)
    level: Level
    model: WritingModel = "deepseek-flash"


class Evidence(BaseModel):
    quote: str = Field(min_length=1, max_length=500)
    category: Literal["task", "content", "coherence", "grammar", "vocabulary", "expression"]
    polarity: Literal["supports", "limits"]
    severity: Literal["minor", "major"]
    explanation: str = Field(min_length=1, max_length=1000)

    @field_validator("quote", mode="before")
    @classmethod
    def truncate_overlong_quote(cls, value: object) -> object:
        if isinstance(value, str) and len(value) > 500:
            return value[:500]
        return value


class RaterResult(BaseModel):
    rater: RaterRole
    pass_index: int = Field(ge=1, le=5)
    score: int = Field(ge=1, le=15)
    band: int
    decision: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def normalize_band(self) -> "RaterResult":
        self.band = score_band(self.score)
        return self


class EvidenceReport(BaseModel):
    agent: Literal["language", "task_content", "coherence"]
    findings: list[Evidence] = Field(default_factory=list, max_length=20)
    summary: str = Field(min_length=1, max_length=2000)


class CriticResult(BaseModel):
    disagreement_sources: list[str] = Field(default_factory=list, max_length=10)
    strict_overreach: list[str] = Field(default_factory=list, max_length=10)
    lenient_overreach: list[str] = Field(default_factory=list, max_length=10)
    missed_evidence: list[str] = Field(default_factory=list, max_length=10)
    recommendation: str = Field(min_length=1, max_length=2000)


class FinalResult(BaseModel):
    score: int = Field(ge=1, le=15)
    band: int
    route: Literal["stable_fusion", "chief_examiner", "invalid"]
    summary: str
    model: WritingModel = "deepseek-flash"
    strengths: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_band(self) -> "FinalResult":
        if self.route != "invalid":
            self.band = score_band(self.score)
        return self
