from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field


FactCategory = Literal[
    "experience_bullet",
    "project_detail",
    "skill",
    "education",
    "certification",
    "summary",
]


class ProfileFactResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    category: str
    text: str
    source_section: str
    embedding_id: str | None = None
    created_at: datetime


class ProfileFactCreateRequest(BaseModel):
    category: FactCategory = "experience_bullet"
    text: str = Field(min_length=2)
    source_section: str = "Manual Entry"


class ProfileFactUpdateRequest(BaseModel):
    category: FactCategory | None = None
    text: str | None = Field(default=None, min_length=2)
    source_section: str | None = None


class JDRequirementItem(BaseModel):
    requirement: str
    keywords: list[str] = Field(default_factory=list)
    priority: Literal["required", "preferred"] = "required"


class JDAnalysisOutput(BaseModel):
    seniority: str = "mid"
    keywords: list[str] = Field(default_factory=list)
    requirements: list[JDRequirementItem] = Field(default_factory=list)


class WrittenBulletItem(BaseModel):
    section: str = "Experience"
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    jd_keywords_covered: list[str] = Field(default_factory=list)


class ResumeWriterOutput(BaseModel):
    summary: str
    bullets: list[WrittenBulletItem] = Field(default_factory=list)
    changes_made: list[str] = Field(default_factory=list)


class BulletVerificationItem(BaseModel):
    bullet_index: int
    status: Literal["verified", "rephrased_ok", "unsupported"]
    reason: str = ""


class ResumeVerifierOutput(BaseModel):
    verifications: list[BulletVerificationItem] = Field(default_factory=list)


class VerificationReport(BaseModel):
    total_bullets: int
    verified_count: int
    rephrased_ok_count: int
    unsupported_removed_count: int
    hallucination_rate: float
    keyword_coverage_score: float
    missing_requirements: list[str] = Field(default_factory=list)
    unsupported_removed: list[dict[str, str]] = Field(default_factory=list)
    loops_used: int = 1


class ResumeBulletEvidenceResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    section: str
    text: str
    fact_ids: list[str]
    status: str
    jd_keywords: list[str]
    reason: str
    evidence_facts: list[ProfileFactResponse] = Field(default_factory=list)


class DocumentVerificationResponse(BaseModel):
    document_id: uuid.UUID
    verification_report: VerificationReport
    bullets: list[ResumeBulletEvidenceResponse]
