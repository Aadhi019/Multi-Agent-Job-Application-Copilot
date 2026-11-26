from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.tracker import TrackerAgent
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.telemetry import Email
from app.models.user import User
from app.schemas.phase4 import EmailRecordResponse, TrackerSyncRequest, TrackerSyncResponse
from app.services.gmail import GmailServiceError

router = APIRouter(prefix="/emails", tags=["emails"])


def _serialize_email(em: Email) -> EmailRecordResponse:
    return EmailRecordResponse(
        id=em.id,
        gmail_message_id=em.gmail_message_id,
        application_id=em.application_id,
        classification=em.classification,
        subject=em.subject,
        snippet=em.snippet,
        received_at=em.received_at,
    )


@router.get("", response_model=list[EmailRecordResponse])
def list_tracked_emails(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmailRecordResponse]:
    """List synced and classified Gmail messages."""
    emails = db.scalars(
        select(Email).where(Email.user_id == user.id).order_by(desc(Email.received_at))
    ).all()
    return [_serialize_email(em) for em in emails]


@router.post("/sync", response_model=TrackerSyncResponse)
def sync_gmail_emails(
    payload: TrackerSyncRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TrackerSyncResponse:
    """Run TrackerAgent to classify Gmail messages and update matching applications."""
    agent = TrackerAgent()
    try:
        res = agent.run(
            db,
            user,
            max_results=payload.max_results,
            query=payload.query,
            simulated_messages=payload.simulated_messages,
        )
    except GmailServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return TrackerSyncResponse(
        synced_count=int(res["synced_count"]),  # type: ignore[arg-type]
        updated_applications=int(res["updated_applications"]),  # type: ignore[arg-type]
        emails=[_serialize_email(em) for em in res["emails"]],  # type: ignore[arg-type]
    )
