from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.cover_letter import CoverLetterAgent
from app.agents.follow_up import FollowUpAgent
from app.agents.form_filler import FormFillerAgent
from app.agents.interview_prep import InterviewPrepAgent
from app.agents.job_discovery import JobDiscoveryAgent
from app.agents.resume_tailor import ResumeTailorAgent
from app.agents.tracker import TrackerAgent
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.telemetry import AgentRun
from app.models.user import User
from app.schemas.agent import AgentRunResponse, ManualAgentRunRequest

router = APIRouter(tags=["agents"])


@router.post("/agents/{agent_name}/run")
def run_agent_manually(
    agent_name: str,
    payload: ManualAgentRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run a single named agent manually for testing or regeneration."""
    normalized = agent_name.lower().replace("-", "_")

    if normalized in {"job_discovery", "jobdiscoveryagent"}:
        agent = JobDiscoveryAgent()
        result = agent.run(
            db,
            user,
            query=payload.query or "",
            sources=payload.sources,
        )
        return {
            "agent": "JobDiscoveryAgent",
            "discovered_count": result["discovered_count"],
            "agent_run_id": str(result.get("agent_run_id")),
        }

    if normalized in {"resume_tailor", "resumetailoragent"}:
        if not payload.application_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="application_id is required to run ResumeTailorAgent.",
            )
        app = db.get(Application, payload.application_id)
        if app is None or app.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        job = db.get(Job, app.job_id)
        assert job is not None
        doc = ResumeTailorAgent().run(db, user, app, job)
        return {"agent": "ResumeTailorAgent", "document_id": str(doc.id), "version": doc.version}

    if normalized in {"cover_letter", "coverletteragent"}:
        if not payload.application_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="application_id is required to run CoverLetterAgent.",
            )
        app = db.get(Application, payload.application_id)
        if app is None or app.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        job = db.get(Job, app.job_id)
        assert job is not None
        doc = CoverLetterAgent().run(db, user, app, job, tone=payload.tone)
        return {"agent": "CoverLetterAgent", "document_id": str(doc.id), "version": doc.version}

    if normalized in {"form_filler", "formfilleragent"}:
        if not payload.application_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="application_id is required to run FormFillerAgent.",
            )
        app = db.get(Application, payload.application_id)
        if app is None or app.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        job = db.get(Job, app.job_id)
        assert job is not None
        doc, report = FormFillerAgent().run(db, user, app, job)
        return {
            "agent": "FormFillerAgent",
            "document_id": str(doc.id),
            "status": report.status,
            "filled_count": len(report.filled_fields),
        }

    if normalized in {"follow_up", "followupagent"}:
        if not payload.application_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="application_id is required to run FollowUpAgent.",
            )
        app = db.get(Application, payload.application_id)
        if app is None or app.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        job = db.get(Job, app.job_id)
        assert job is not None
        doc = FollowUpAgent().draft_followup(db, user, app, job)
        return {"agent": "FollowUpAgent", "document_id": str(doc.id), "version": doc.version}

    if normalized in {"tracker", "trackeragent"}:
        res = TrackerAgent().run(db, user)
        return {
            "agent": "TrackerAgent",
            "synced_count": res["synced_count"],
            "updated_applications": res["updated_applications"],
        }

    if normalized in {"interview_prep", "interviewprepagent"}:
        if not payload.application_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="application_id is required to run InterviewPrepAgent.",
            )
        app = db.get(Application, payload.application_id)
        if app is None or app.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        job = db.get(Job, app.job_id)
        assert job is not None
        doc = InterviewPrepAgent().run(db, user, app, job)
        return {"agent": "InterviewPrepAgent", "document_id": str(doc.id), "version": doc.version}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown or unsupported agent '{agent_name}'.",
    )


@router.get("/agent-runs", response_model=list[AgentRunResponse])
def list_agent_runs(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AgentRunResponse]:
    """List recent agent execution logs."""
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == user.id)
        .order_by(desc(AgentRun.created_at))
        .limit(limit)
    ).all()
    return [
        AgentRunResponse(
            id=r.id,
            agent_name=r.agent_name,
            input_summary=r.input_summary,
            output_summary=r.output_summary,
            status=r.status,
            latency_ms=r.latency_ms,
            tokens_used=r.tokens_used,
            error=r.error,
            created_at=r.created_at,
        )
        for r in runs
    ]
