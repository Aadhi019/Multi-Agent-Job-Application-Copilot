import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.resume_tailor import ResumeTailorAgent
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.application import Application, Document
from app.models.evidence import ProfileFact, ResumeBullet
from app.models.job import Job
from app.models.user import User
from app.schemas.evidence import (
    DocumentVerificationResponse,
    ProfileFactResponse,
    ResumeBulletEvidenceResponse,
    VerificationReport,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _serialize_fact(f: ProfileFact) -> ProfileFactResponse:
    return ProfileFactResponse(
        id=f.id,
        user_id=f.user_id,
        category=f.category,
        text=f.text,
        source_section=f.source_section,
        embedding_id=f.embedding_id,
        created_at=f.created_at,
    )


def _serialize_bullet(b: ResumeBullet, fact_map: dict[str, ProfileFact]) -> ResumeBulletEvidenceResponse:
    evidence = [_serialize_fact(fact_map[fid]) for fid in (b.fact_ids or []) if fid in fact_map]
    return ResumeBulletEvidenceResponse(
        id=b.id,
        document_id=b.document_id,
        section=b.section,
        text=b.text,
        fact_ids=[str(fid) for fid in (b.fact_ids or [])],
        status=b.status,
        jd_keywords=list(b.jd_keywords or []),
        reason=b.reason or "",
        evidence_facts=evidence,
    )


@router.get("/{document_id}/verification", response_model=DocumentVerificationResponse)
def get_document_verification(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentVerificationResponse:
    """Return per-bullet verification status and cited profile_facts evidence for a resume document."""
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    bullets = list(
        db.scalars(
            select(ResumeBullet)
            .where(ResumeBullet.document_id == doc.id)
            .order_by(ResumeBullet.created_at.asc())
        ).all()
    )
    facts = list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == user.id)).all())
    fact_map = {str(f.id): f for f in facts}

    raw_report = (doc.doc_metadata or {}).get("verification_report")
    if raw_report:
        report = VerificationReport.model_validate(raw_report)
    else:
        verified_c = sum(1 for b in bullets if b.status == "verified")
        rephrased_c = sum(1 for b in bullets if b.status == "rephrased_ok")
        unsupported_c = sum(1 for b in bullets if b.status == "unsupported")
        report = VerificationReport(
            total_bullets=len(bullets),
            verified_count=verified_c,
            rephrased_ok_count=rephrased_c,
            unsupported_removed_count=unsupported_c,
            hallucination_rate=round(unsupported_c / max(len(bullets), 1), 4),
            keyword_coverage_score=float((doc.doc_metadata or {}).get("keyword_coverage_score", 0.0)),
            missing_requirements=list((doc.doc_metadata or {}).get("missing_requirements", [])),
        )

    return DocumentVerificationResponse(
        document_id=doc.id,
        verification_report=report,
        bullets=[_serialize_bullet(b, fact_map) for b in bullets],
    )


@router.post("/{document_id}/bullets/{bullet_id}/regenerate", response_model=ResumeBulletEvidenceResponse)
def regenerate_resume_bullet(
    document_id: uuid.UUID,
    bullet_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeBulletEvidenceResponse:
    """Regenerate a single resume bullet strictly from its cited profile facts and re-verify."""
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    bullet = db.get(ResumeBullet, bullet_id)
    if bullet is None or bullet.document_id != doc.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bullet not found.")

    job: Job | None = None
    if doc.application_id:
        app = db.get(Application, doc.application_id)
        if app:
            job = db.get(Job, app.job_id)

    updated = ResumeTailorAgent().regenerate_single_bullet(db, user, bullet, job=job)
    facts = list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == user.id)).all())
    fact_map = {str(f.id): f for f in facts}
    return _serialize_bullet(updated, fact_map)
