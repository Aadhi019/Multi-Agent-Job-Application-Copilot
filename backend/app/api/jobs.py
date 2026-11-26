from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.job_discovery import JobDiscoveryAgent
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.job import Job
from app.models.user import User
from app.schemas.job import (
    JobDiscoveryRequest,
    JobDiscoveryResponse,
    JobImportUrlRequest,
    JobResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _serialize_job(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        source=job.source,
        title=job.title,
        company=job.company,
        location=job.location,
        url=job.url,
        description=job.description,
        fit_score=job.fit_score,
        fit_reason=job.fit_reason,
        discovered_at=job.discovered_at,
    )


@router.post("/discover", response_model=JobDiscoveryResponse)
def discover_jobs(
    payload: JobDiscoveryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobDiscoveryResponse:
    """Run JobDiscoveryAgent against configured public APIs/RSS feeds and rank by fit."""
    agent = JobDiscoveryAgent()
    result = agent.run(
        db,
        user,
        target_roles=payload.target_roles,
        skills=payload.skills,
        location=payload.location,
        remote_preference=payload.remote_preference,
        sources=payload.sources,
        rss_urls=payload.rss_urls,
        query=payload.query,
        limit=payload.limit,
    )
    return JobDiscoveryResponse(
        discovered_count=result["discovered_count"],
        deduplicated_count=result["deduplicated_count"],
        jobs=[_serialize_job(j) for j in result["jobs"]],
        agent_run_id=result.get("agent_run_id"),
    )


@router.get("", response_model=list[JobResponse])
def list_jobs(
    min_score: float | None = Query(default=None, ge=0, le=100),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    """List discovered jobs ordered by fit score descending."""
    stmt = select(Job).where(Job.user_id == user.id)
    if min_score is not None:
        stmt = stmt.where(Job.fit_score >= min_score)
    if source:
        stmt = stmt.where(Job.source == source)
    stmt = stmt.order_by(desc(Job.fit_score), desc(Job.discovered_at))

    jobs = db.scalars(stmt).all()
    if search:
        term = search.strip().lower()
        jobs = [
            j
            for j in jobs
            if term in j.title.lower() or term in j.company.lower() or term in j.description.lower()
        ]
    return [_serialize_job(j) for j in jobs]


@router.post("/import-url", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def import_job_url(
    payload: JobImportUrlRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    """Import a user-supplied job URL (or pasted details) and compute fit score."""
    agent = JobDiscoveryAgent()
    try:
        job = agent.import_url(
            db,
            user,
            url=payload.url,
            title=payload.title,
            company=payload.company,
            location=payload.location,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_job(job)


@router.post("/rescore", response_model=list[JobResponse])
def rescore_jobs(
    use_llm: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    """Re-score all saved jobs against the user's latest profile and master resume."""
    jobs = JobDiscoveryAgent().rescore_user_jobs(db, user, use_llm=use_llm)
    return [_serialize_job(j) for j in jobs]
