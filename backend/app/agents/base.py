from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from app.models.telemetry import AgentRun
from app.services.ws_manager import ws_manager


def truncate_summary(text: str, max_len: int = 400) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[: max_len - 3]}..."


def record_agent_run(
    db: Session,
    *,
    user_id: uuid.UUID,
    agent_name: str,
    input_summary: str,
    output_summary: str,
    status: str,
    latency_ms: int | None = None,
    tokens_used: int | None = None,
    error: str | None = None,
    run_id: str = "global",
) -> AgentRun:
    """Persist an agent execution log row to PostgreSQL and broadcast WS telemetry."""
    run = AgentRun(
        user_id=user_id,
        agent_name=agent_name,
        input_summary=truncate_summary(input_summary, 500),
        output_summary=truncate_summary(output_summary, 500),
        status=status,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        error=error,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    ws_manager.emit_sync(
        run_id=run_id,
        agent_name=agent_name,
        step="completed",
        status=status,
        message=truncate_summary(output_summary, 240),
    )
    return run
