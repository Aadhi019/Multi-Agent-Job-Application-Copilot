from pydantic import BaseModel, Field

from app.schemas.agent import AgentRunResponse


class StarOutline(BaseModel):
    question: str
    mapped_project_or_role: str = ""
    situation: str
    task: str
    action: str
    result: str


class InterviewPrepOutput(BaseModel):
    technical_questions: list[str] = Field(default_factory=list)
    behavioral_questions: list[str] = Field(default_factory=list)
    star_outlines: list[StarOutline] = Field(default_factory=list)
    company_research_notes: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)


class AgentMetricSummary(BaseModel):
    agent_name: str
    total_runs: int
    success_count: int
    failed_count: int
    success_rate: float
    avg_latency_ms: float | None = None
    total_tokens: int


class AnalyticsSummaryResponse(BaseModel):
    total_jobs: int
    total_applications: int
    counts_by_status: dict[str, int]
    response_rate: float
    avg_time_per_application_seconds: float | None = None
    agent_metrics: list[AgentMetricSummary]
    recent_agent_runs: list[AgentRunResponse]
