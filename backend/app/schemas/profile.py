from typing import Literal
import uuid

from pydantic import BaseModel, Field


class ExperienceItem(BaseModel):
    company: str = ""
    title: str = ""
    start_date: str = ""
    end_date: str = ""
    location: str = ""
    highlights: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str = ""
    description: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    url: str = ""
    highlights: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: str = ""
    degree: str = ""
    graduation_year: str = ""
    gpa: str = ""


class PreferencesSchema(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] = "any"
    cover_letter_tone: Literal["formal", "friendly", "concise"] = "formal"
    job_sources: list[str] = Field(default_factory=lambda: ["remotive", "manual"])
    phone: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""


class ParsedProfileFields(BaseModel):
    name: str | None = None
    email: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    skills: list[str]
    experience: list[ExperienceItem]
    projects: list[ProjectItem]
    education: list[EducationItem]
    preferences: PreferencesSchema
    master_resume_text: str


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    skills: list[str] | None = None
    experience: list[ExperienceItem] | None = None
    projects: list[ProjectItem] | None = None
    education: list[EducationItem] | None = None
    preferences: PreferencesSchema | None = None
    master_resume_text: str | None = None


class ResumeUploadResponse(BaseModel):
    filename: str
    extracted_chars: int
    parser_mode: Literal["groq", "heuristic", "text_only"]
    parsed_fields: ParsedProfileFields
    profile: ProfileResponse
