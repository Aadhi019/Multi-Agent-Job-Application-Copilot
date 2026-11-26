from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.application import Application
from app.models.job import Job
from app.models.telemetry import AgentRun
from app.models.user import User
from app.schemas.agent import AgentRunResponse
from app.schemas.phase5 import AgentMetricSummary, AnalyticsSummaryResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def get_analytics_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Return pipeline counts, response rate, average agent latency, and recent runs."""
    total_jobs = db.scalar(select(func.count(Job.id)).where(Job.user_id == user.id)) or 0
    apps = db.scalars(select(Application).where(Application.user_id == user.id)).all()

    counts_by_status: dict[str, int] = defaultdict(int)
    for app in apps:
        counts_by_status[app.status] += 1

    submitted_or_progressed = sum(
        counts_by_status.get(s, 0) for s in ("applied", "interview", "offer", "rejected")
    )
    responded = sum(counts_by_status.get(s, 0) for s in ("interview", "offer", "rejected"))
    response_rate = (
        round((responded / submitted_or_progressed) * 100.0, 1)
        if submitted_or_progressed > 0
        else 0.0
    )

    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == user.id)
        .order_by(desc(AgentRun.created_at))
    ).all()

    grouped: dict[str, list[AgentRun]] = defaultdict(list)
    for r in runs:
        grouped[r.agent_name].append(r)

    agent_metrics: list[AgentMetricSummary] = []
    total_agent_latency_ms = 0
    for name, items in sorted(grouped.items()):
        total = len(items)
        succ = sum(1 for i in items if i.status in ("success", "partial"))
        fail = total - succ
        latencies = [i.latency_ms for i in items if i.latency_ms is not None]
        avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else None
        total_agent_latency_ms += sum(latencies)
        tokens = sum(i.tokens_used or 0 for i in items)
        agent_metrics.append(
            AgentMetricSummary(
                agent_name=name,
                total_runs=total,
                success_count=succ,
                failed_count=fail,
                success_rate=round((succ / total) * 100.0, 1) if total else 0.0,
                avg_latency_ms=avg_lat,
                total_tokens=tokens,
            )
        )

    avg_time_per_app_s = (
        round((total_agent_latency_ms / 1000.0) / len(apps), 2) if apps and total_agent_latency_ms else None
    )

    recent_runs = [
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
        for r in runs[:10]
    ]

    return AnalyticsSummaryResponse(
        total_jobs=total_jobs,
        total_applications=len(apps),
        counts_by_status=dict(counts_by_status),
        response_rate=response_rate,
        avg_time_per_application_seconds=avg_time_per_app_s,
        agent_metrics=agent_metrics,
        recent_agent_runs=recent_runs,
    )
