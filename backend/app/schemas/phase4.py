from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field


class FormFieldReportItem(BaseModel):
    field_name: str
    label: str
    field_type: str
    status: Literal["filled", "unfilled", "uploaded", "skipped"]
    value_preview: str = ""


class GeneratedAnswerItem(BaseModel):
    question: str
    answer: str


class FormFillRequest(BaseModel):
    url: str | None = None
    headless: bool = True


class FormFillReport(BaseModel):
    url: str
    status: Literal["ready_for_review", "blocked", "failed"]
    filled_fields: list[FormFieldReportItem] = Field(default_factory=list)
    unfilled_fields: list[FormFieldReportItem] = Field(default_factory=list)
    generated_answers: list[GeneratedAnswerItem] = Field(default_factory=list)
    screenshot_paths: list[str] = Field(default_factory=list)
    screenshot_urls: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    stopped_before_submit: bool = True
    notes: str = ""


class FreeTextAnswersOutput(BaseModel):
    answers: list[GeneratedAnswerItem] = Field(default_factory=list)


class FollowUpRequest(BaseModel):
    followup_type: Literal["after_applying", "after_interview", "thank_you"] = "after_applying"
    to_email: str = ""
    extra_context: str = ""


class FollowUpLLMOutput(BaseModel):
    subject: str
    body: str
    recommended_send_window: str = ""


class FollowUpApproveRequest(BaseModel):
    to_email: str | None = None
    subject: str | None = None
    body: str | None = None


class EmailClassificationOutput(BaseModel):
    classification: Literal["applied", "interview", "rejected", "offer", "other"]
    matched_company: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    summary: str = ""


class TrackerSyncMessage(BaseModel):
    gmail_message_id: str
    subject: str
    from_email: str = ""
    snippet: str = ""


class TrackerSyncRequest(BaseModel):
    max_results: int = Field(default=20, ge=1, le=50)
    query: str = ""
    simulated_messages: list[TrackerSyncMessage] | None = None


class EmailRecordResponse(BaseModel):
    id: uuid.UUID
    gmail_message_id: str
    application_id: uuid.UUID | None = None
    classification: str
    subject: str
    snippet: str
    received_at: datetime


class TrackerSyncResponse(BaseModel):
    synced_count: int
    updated_applications: int
    emails: list[EmailRecordResponse]
