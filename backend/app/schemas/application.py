from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field

from app.schemas.job import JobResponse


class TailoredExperienceEntry(BaseModel):
    company: str
    title: str
    start_date: str = ""
    end_date: str = ""
    location: str = ""
    highlights: list[str] = Field(default_factory=list)


class TailoredProjectEntry(BaseModel):
    name: str
    description: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class TailoredResumeOutput(BaseModel):
    summary: str
    skills_highlighted: list[str] = Field(default_factory=list)
    experience: list[TailoredExperienceEntry] = Field(default_factory=list)
    projects: list[TailoredProjectEntry] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    jd_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    keyword_coverage_score: float = Field(ge=0, le=100)
    changes_made: list[str] = Field(default_factory=list)


class CoverLetterOutput(BaseModel):
    subject: str
    greeting: str
    paragraphs: list[str] = Field(min_length=2, max_length=5)
    closing: str
    key_points_used: list[str] = Field(default_factory=list)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID | None = None
    type: str
    content: str
    metadata: dict[str, Any]
    version: int
    created_at: datetime


class ApplicationCreateRequest(BaseModel):
    job_id: uuid.UUID
    cover_letter_tone: Literal["formal", "friendly", "concise"] | None = None
    intent: str = "apply_to_job"


class ApplicationStatusUpdateRequest(BaseModel):
    status: str
    notes: str | None = None


class ApplicationApprovalRequest(BaseModel):
    feedback: str = ""


class CoverLetterUpdateRequest(BaseModel):
    content: str
    tone: Literal["formal", "friendly", "concise"] | None = None


class ApplicationSummaryResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    status: str
    job_title: str
    company: str
    location: str
    fit_score: float | None = None
    job_url: str
    applied_at: datetime | None = None
    updated_at: datetime
    notes: str


class ApplicationDetailResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    status: str
    resume_version_id: uuid.UUID | None = None
    cover_letter_id: uuid.UUID | None = None
    applied_at: datetime | None = None
    updated_at: datetime
    notes: str
    job: JobResponse
    master_resume_text: str
    documents: list[DocumentResponse]
