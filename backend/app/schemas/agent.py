from datetime import datetime
import uuid

from pydantic import BaseModel


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    agent_name: str
    input_summary: str
    output_summary: str
    status: str
    latency_ms: int | None = None
    tokens_used: int | None = None
    error: str | None = None
    created_at: datetime


class ManualAgentRunRequest(BaseModel):
    job_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    tone: str | None = None
    query: str | None = None
    sources: list[str] | None = None
