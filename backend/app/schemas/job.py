from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class JobDiscoveryRequest(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    location: str = ""
    remote_preference: str = "any"
    sources: list[str] = Field(default_factory=lambda: ["himalayas", "jobicy", "remotive", "arbeitnow"])
    rss_urls: list[str] = Field(default_factory=list)
    query: str = ""
    limit: int = Field(default=15, ge=1, le=50)


class JobImportUrlRequest(BaseModel):
    url: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None


class JobFitScoreOutput(BaseModel):
    fit_score: float = Field(ge=0, le=100)
    fit_reason: str
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: uuid.UUID
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str
    fit_score: float | None = None
    fit_reason: str | None = None
    discovered_at: datetime


class JobDiscoveryResponse(BaseModel):
    discovered_count: int
    deduplicated_count: int
    jobs: list[JobResponse]
    agent_run_id: uuid.UUID | None = None
