from typing import Any, Literal, TypedDict


IntentType = Literal[
    "apply_to_job",
    "discover_jobs",
    "prep_interview",
    "check_status",
    "followup",
]


class CopilotState(TypedDict, total=False):
    """Shared LangGraph state across the orchestrator and specialized agents."""

    user_id: str
    intent: IntentType
    profile: dict[str, Any]
    master_resume_text: str
    current_job: dict[str, Any]

    tailored_resume: dict[str, Any]
    cover_letter: dict[str, Any]
    form_fill_report: dict[str, Any]
    interview_prep: dict[str, Any]
    follow_up_drafts: list[dict[str, Any]]

    application_id: str | None
    status: str
    errors: list[str]
    messages: list[str]
    next_step: str

    # Orchestration & HITL control metadata
    retry_counts: dict[str, int]
    discovery_params: dict[str, Any]
    discovery_result: dict[str, Any]
    cover_letter_tone: str
    run_form_filler: bool
    followup_type: str
    followup_to_email: str
    tracker_result: dict[str, Any]
    approval_decision: str | None
    approval_feedback: str
