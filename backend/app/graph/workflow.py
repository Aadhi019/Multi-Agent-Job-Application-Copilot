from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.orm import Session

from app.agents.cover_letter import CoverLetterAgent
from app.agents.follow_up import FollowUpAgent
from app.agents.form_filler import FormFillerAgent
from app.agents.interview_prep import InterviewPrepAgent
from app.agents.job_discovery import JobDiscoveryAgent
from app.agents.resume_tailor import ResumeTailorAgent
from app.agents.tracker import TrackerAgent
from app.graph.state import CopilotState
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

MAX_NODE_RETRIES = 2
_CHECKPOINTER = MemorySaver()


def get_checkpointer() -> MemorySaver:
    return _CHECKPOINTER


def _get_db_and_user(state: CopilotState, config: RunnableConfig) -> tuple[Session, User]:
    configurable = config.get("configurable", {})
    db: Session | None = configurable.get("db")
    if db is None:
        raise RuntimeError("Database session missing in LangGraph RunnableConfig['configurable']['db'].")
    user = db.get(User, uuid.UUID(state["user_id"]))
    if user is None:
        raise RuntimeError(f"User {state['user_id']} not found.")
    return db, user


def orchestrator_node(state: CopilotState) -> dict[str, Any]:
    """Read user intent + current artifacts and decide next step with retry/fallback bounds."""
    intent = state.get("intent", "apply_to_job")
    retries = dict(state.get("retry_counts") or {})
    messages = list(state.get("messages") or [])

    if intent == "discover_jobs":
        if state.get("discovery_result"):
            return {"next_step": "end", "status": "completed"}
        if retries.get("job_discovery", 0) > MAX_NODE_RETRIES:
            return {"next_step": "end", "status": "failed"}
        return {"next_step": "job_discovery", "status": "discovering"}

    if intent == "apply_to_job":
        if not state.get("tailored_resume"):
            if retries.get("resume_tailor", 0) > MAX_NODE_RETRIES:
                messages.append("Resume tailoring exceeded max retries; moving to fallback end.")
                return {"next_step": "end", "status": "failed", "messages": messages}
            return {"next_step": "resume_tailor", "status": "tailoring"}

        if not state.get("cover_letter"):
            if retries.get("cover_letter", 0) > MAX_NODE_RETRIES:
                messages.append("Cover letter generation exceeded max retries; pausing for review.")
                return {"next_step": "awaiting_approval", "status": "awaiting_approval", "messages": messages}
            return {"next_step": "cover_letter", "status": "drafting_cover_letter"}

        if state.get("run_form_filler") and not state.get("form_fill_report"):
            if retries.get("form_filler", 0) > MAX_NODE_RETRIES:
                messages.append("Form filler exceeded max retries; pausing for manual review.")
                return {"next_step": "awaiting_approval", "status": "awaiting_approval", "messages": messages}
            return {"next_step": "form_filler", "status": "filling_form"}

        if state.get("approval_decision") is None:
            return {"next_step": "awaiting_approval", "status": "awaiting_approval"}

        return {"next_step": "end", "status": state.get("status", "ready_to_submit")}

    if intent == "followup":
        if not state.get("follow_up_drafts"):
            if retries.get("follow_up", 0) > MAX_NODE_RETRIES:
                return {"next_step": "end", "status": "failed"}
            return {"next_step": "follow_up", "status": "drafting_followup"}
        if state.get("approval_decision") is None:
            return {"next_step": "awaiting_approval", "status": "awaiting_approval"}
        return {"next_step": "end", "status": state.get("status", "completed")}

    if intent == "check_status":
        if state.get("tracker_result"):
            return {"next_step": "end", "status": "completed"}
        if retries.get("tracker", 0) > MAX_NODE_RETRIES:
            return {"next_step": "end", "status": "failed"}
        return {"next_step": "tracker", "status": "syncing_emails"}

    if intent == "prep_interview":
        if state.get("interview_prep"):
            return {"next_step": "end", "status": "completed"}
        if retries.get("interview_prep", 0) > MAX_NODE_RETRIES:
            return {"next_step": "end", "status": "failed"}
        return {"next_step": "interview_prep", "status": "preparing_interview"}

    messages.append(f"Intent '{intent}' reached orchestrator.")
    return {"next_step": "end", "status": "completed", "messages": messages}


def job_discovery_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    try:
        db, user = _get_db_and_user(state, config)
        params = state.get("discovery_params") or {}
        agent = JobDiscoveryAgent()
        result = agent.run(
            db,
            user,
            target_roles=params.get("target_roles"),
            skills=params.get("skills"),
            location=params.get("location", ""),
            remote_preference=params.get("remote_preference", "any"),
            sources=params.get("sources"),
            rss_urls=params.get("rss_urls"),
            query=params.get("query", ""),
            limit=params.get("limit", 15),
        )
        messages.append(
            f"Discovered {result['discovered_count']} new jobs ({result['deduplicated_count']} deduplicated)."
        )
        return {
            "discovery_result": {
                "discovered_count": result["discovered_count"],
                "deduplicated_count": result["deduplicated_count"],
                "job_ids": [str(j.id) for j in result["jobs"]],
                "agent_run_id": str(result["agent_run_id"]) if result.get("agent_run_id") else None,
            },
            "messages": messages,
        }
    except Exception as exc:
        retries["job_discovery"] = retries.get("job_discovery", 0) + 1
        errors.append(f"job_discovery: {exc}")
        return {"retry_counts": retries, "errors": errors}


def resume_tailor_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    try:
        db, user = _get_db_and_user(state, config)
        app_id = uuid.UUID(str(state["application_id"]))
        application = db.get(Application, app_id)
        if application is None:
            raise RuntimeError(f"Application {app_id} not found")
        job = db.get(Job, application.job_id)
        if job is None:
            raise RuntimeError(f"Job {application.job_id} not found")

        agent = ResumeTailorAgent()
        doc = agent.run(db, user, application, job)
        messages.append(
            f"Tailored resume v{doc.version} (coverage {doc.doc_metadata.get('keyword_coverage_score', 0)}%)."
        )
        return {
            "tailored_resume": {
                "document_id": str(doc.id),
                "version": doc.version,
                "content": doc.content,
                "metadata": doc.doc_metadata,
            },
            "messages": messages,
        }
    except Exception as exc:
        retries["resume_tailor"] = retries.get("resume_tailor", 0) + 1
        errors.append(f"resume_tailor: {exc}")
        return {"retry_counts": retries, "errors": errors}


def cover_letter_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    try:
        db, user = _get_db_and_user(state, config)
        app_id = uuid.UUID(str(state["application_id"]))
        application = db.get(Application, app_id)
        if application is None:
            raise RuntimeError(f"Application {app_id} not found")
        job = db.get(Job, application.job_id)
        if job is None:
            raise RuntimeError(f"Job {application.job_id} not found")

        agent = CoverLetterAgent()
        doc = agent.run(db, user, application, job, tone=state.get("cover_letter_tone"))
        application.status = "awaiting_approval"
        db.add(application)
        db.commit()

        messages.append(f"Generated cover letter v{doc.version} ({doc.doc_metadata.get('tone', 'formal')}).")
        return {
            "cover_letter": {
                "document_id": str(doc.id),
                "version": doc.version,
                "content": doc.content,
                "metadata": doc.doc_metadata,
            },
            "status": "awaiting_approval",
            "messages": messages,
        }
    except Exception as exc:
        retries["cover_letter"] = retries.get("cover_letter", 0) + 1
        errors.append(f"cover_letter: {exc}")
        return {"retry_counts": retries, "errors": errors}


def form_filler_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    try:
        db, user = _get_db_and_user(state, config)
        app_id = uuid.UUID(str(state["application_id"]))
        application = db.get(Application, app_id)
        if application is None:
            raise RuntimeError(f"Application {app_id} not found")
        job = db.get(Job, application.job_id)
        if job is None:
            raise RuntimeError(f"Job {application.job_id} not found")

        target_url = (state.get("current_job") or {}).get("url") or job.url
        _, report = FormFillerAgent().run(db, user, application, job, target_url=target_url)
        messages.append(
            f"FormFillerAgent finished with status={report.status} (filled={len(report.filled_fields)})."
        )
        return {"form_fill_report": report.model_dump(), "messages": messages}
    except Exception as exc:
        retries["form_filler"] = retries.get("form_filler", 0) + 1
        errors.append(f"form_filler: {exc}")
        return {"retry_counts": retries, "errors": errors}


def follow_up_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    try:
        db, user = _get_db_and_user(state, config)
        app_id = uuid.UUID(str(state["application_id"]))
        application = db.get(Application, app_id)
        if application is None:
            raise RuntimeError(f"Application {app_id} not found")
        job = db.get(Job, application.job_id)
        if job is None:
            raise RuntimeError(f"Job {application.job_id} not found")

        doc = FollowUpAgent().draft_followup(
            db,
            user,
            application,
            job,
            followup_type=state.get("followup_type", "after_applying"),
            to_email=state.get("followup_to_email", ""),
        )
        messages.append(f"Drafted follow-up email v{doc.version} awaiting human approval.")
        return {
            "follow_up_drafts": [
                {
                    "document_id": str(doc.id),
                    "version": doc.version,
                    "content": doc.content,
                    "metadata": doc.doc_metadata,
                }
            ],
            "messages": messages,
        }
    except Exception as exc:
        retries["follow_up"] = retries.get("follow_up", 0) + 1
        errors.append(f"follow_up: {exc}")
        return {"retry_counts": retries, "errors": errors}


def tracker_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    try:
        db, user = _get_db_and_user(state, config)
        res = TrackerAgent().run(db, user)
        messages.append(
            f"TrackerAgent synced {res['synced_count']} new email(s), updated {res['updated_applications']} application(s)."
        )
        return {
            "tracker_result": {
                "synced_count": res["synced_count"],
                "updated_applications": res["updated_applications"],
            },
            "messages": messages,
        }
    except Exception as exc:
        retries["tracker"] = retries.get("tracker", 0) + 1
        errors.append(f"tracker: {exc}")
        return {"retry_counts": retries, "errors": errors}


def interview_prep_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    retries = dict(state.get("retry_counts") or {})
    errors = list(state.get("errors") or [])
    messages = list(state.get("messages") or [])
    run_id = str(state.get("application_id") or "global")
    try:
        db, user = _get_db_and_user(state, config)
        app_id = uuid.UUID(str(state["application_id"]))
        application = db.get(Application, app_id)
        if application is None:
            raise RuntimeError(f"Application {app_id} not found")
        job = db.get(Job, application.job_id)
        if job is None:
            raise RuntimeError(f"Job {application.job_id} not found")

        ws_manager.emit_sync(
            run_id=run_id,
            agent_name="InterviewPrepAgent",
            step="running",
            status="running",
            message=f"Generating interview prep for {job.title} at {job.company}",
        )
        doc = InterviewPrepAgent().run(db, user, application, job)
        messages.append(f"Generated interview prep v{doc.version}.")
        return {
            "interview_prep": {
                "document_id": str(doc.id),
                "version": doc.version,
                "metadata": doc.doc_metadata,
            },
            "messages": messages,
        }
    except Exception as exc:
        retries["interview_prep"] = retries.get("interview_prep", 0) + 1
        errors.append(f"interview_prep: {exc}")
        return {"retry_counts": retries, "errors": errors}


def awaiting_approval_node(state: CopilotState, config: RunnableConfig) -> dict[str, Any]:
    """Pause the LangGraph execution with interrupt() until user approves or rejects in UI."""
    ws_manager.emit_sync(
        run_id=str(state.get("application_id") or "global"),
        agent_name="Orchestrator",
        step="awaiting_approval",
        status="awaiting_approval",
        message="Paused at human approval checkpoint.",
    )
    resume_payload = interrupt(
        {
            "application_id": state.get("application_id"),
            "status": "awaiting_approval",
            "prompt": "Review tailored documents, form fill report, or email draft, then approve or reject.",
        }
    )

    decision = "approved"
    feedback = ""
    if isinstance(resume_payload, dict):
        decision = str(resume_payload.get("decision", "approved"))
        feedback = str(resume_payload.get("feedback", ""))
    elif isinstance(resume_payload, str):
        decision = resume_payload

    new_status = "ready_to_submit" if decision == "approved" else "rejected"
    messages = list(state.get("messages") or [])
    messages.append(f"Human decision: {decision}" + (f" ({feedback})" if feedback else ""))

    try:
        db, _ = _get_db_and_user(state, config)
        if state.get("application_id"):
            application = db.get(Application, uuid.UUID(str(state["application_id"])))
            if application is not None:
                application.status = new_status
                if feedback:
                    application.notes = (
                        f"{application.notes}\n[{decision}] {feedback}".strip()
                        if application.notes
                        else f"[{decision}] {feedback}"
                    )
                db.add(application)
                db.commit()
    except Exception as exc:
        logger.warning("Failed updating application on approval resume: %s", exc)

    return {
        "approval_decision": decision,
        "approval_feedback": feedback,
        "status": new_status,
        "messages": messages,
    }


def _route_from_orchestrator(state: CopilotState) -> str:
    step = state.get("next_step", "end")
    if step in {
        "job_discovery",
        "resume_tailor",
        "cover_letter",
        "form_filler",
        "follow_up",
        "tracker",
        "interview_prep",
        "awaiting_approval",
    }:
        return step
    return "end"


def build_copilot_graph():
    """Compile the LangGraph workflow with checkpointing for human-in-the-loop interrupts."""
    builder = StateGraph(CopilotState)
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("job_discovery", job_discovery_node)
    builder.add_node("resume_tailor", resume_tailor_node)
    builder.add_node("cover_letter", cover_letter_node)
    builder.add_node("form_filler", form_filler_node)
    builder.add_node("follow_up", follow_up_node)
    builder.add_node("tracker", tracker_node)
    builder.add_node("interview_prep", interview_prep_node)
    builder.add_node("awaiting_approval", awaiting_approval_node)

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges(
        "orchestrator",
        _route_from_orchestrator,
        {
            "job_discovery": "job_discovery",
            "resume_tailor": "resume_tailor",
            "cover_letter": "cover_letter",
            "form_filler": "form_filler",
            "follow_up": "follow_up",
            "tracker": "tracker",
            "interview_prep": "interview_prep",
            "awaiting_approval": "awaiting_approval",
            "end": END,
        },
    )
    builder.add_edge("job_discovery", "orchestrator")
    builder.add_edge("resume_tailor", "orchestrator")
    builder.add_edge("cover_letter", "orchestrator")
    builder.add_edge("form_filler", "orchestrator")
    builder.add_edge("follow_up", "orchestrator")
    builder.add_edge("tracker", "orchestrator")
    builder.add_edge("interview_prep", "orchestrator")
    builder.add_edge("awaiting_approval", "orchestrator")

    return builder.compile(checkpointer=_CHECKPOINTER)


copilot_graph = build_copilot_graph()


def resume_application_approval(
    *,
    thread_id: str,
    decision: str,
    feedback: str,
    db: Session,
) -> dict[str, Any] | None:
    """Resume a checkpointed application workflow if present in the checkpointer."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id, "db": db}}
    snapshot = copilot_graph.get_state(config)
    if snapshot and snapshot.next:
        return copilot_graph.invoke(
            Command(resume={"decision": decision, "feedback": feedback}),
            config=config,
        )
    return None
