import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.agents.follow_up import FollowUpAgent
from app.agents.form_filler import FormFillerAgent
from app.agents.interview_prep import InterviewPrepAgent
from app.agents.resume_tailor import (
    render_resume_docx,
    render_resume_pdf,
)
from app.api.deps import get_current_user
from app.api.jobs import _serialize_job
from app.core.db import get_db
from app.graph.workflow import copilot_graph, resume_application_approval
from app.models.application import Application, Document
from app.models.job import Job
from app.models.user import User
from app.schemas.application import (
    ApplicationApprovalRequest,
    ApplicationCreateRequest,
    ApplicationDetailResponse,
    ApplicationStatusUpdateRequest,
    ApplicationSummaryResponse,
    CoverLetterUpdateRequest,
    DocumentResponse,
    TailoredResumeOutput,
)
from app.schemas.phase4 import (
    FollowUpApproveRequest,
    FollowUpRequest,
    FormFillReport,
    FormFillRequest,
)
from app.services.gmail import GmailServiceError
from app.services.playwright import ARTIFACTS_ROOT

router = APIRouter(prefix="/applications", tags=["applications"])


def _serialize_doc(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        application_id=doc.application_id,
        type=doc.type,
        content=doc.content,
        metadata=dict(doc.doc_metadata or {}),
        version=doc.version,
        created_at=doc.created_at,
    )


def _serialize_detail(user: User, app: Application, job: Job, docs: list[Document]) -> ApplicationDetailResponse:
    master_resume = (user.profile.master_resume_text if user.profile else "") or ""
    return ApplicationDetailResponse(
        id=app.id,
        job_id=app.job_id,
        status=app.status,
        resume_version_id=app.resume_version_id,
        cover_letter_id=app.cover_letter_id,
        applied_at=app.applied_at,
        updated_at=app.updated_at,
        notes=app.notes or "",
        job=_serialize_job(job),
        master_resume_text=master_resume,
        documents=[_serialize_doc(d) for d in docs],
    )


@router.post("", response_model=ApplicationDetailResponse, status_code=status.HTTP_201_CREATED)
def start_application_workflow(
    payload: ApplicationCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailResponse:
    """Create an application and run LangGraph apply_to_job workflow until awaiting_approval."""
    job = db.get(Job, payload.job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    app = Application(user_id=user.id, job_id=job.id, status="tailoring")
    db.add(app)
    db.commit()
    db.refresh(app)

    profile = user.profile
    prefs = (profile.preferences if profile else {}) or {}
    tone = payload.cover_letter_tone or prefs.get("cover_letter_tone", "formal")

    initial_state = {
        "user_id": str(user.id),
        "intent": payload.intent,
        "profile": {
            "skills": list((profile.skills if profile else []) or []),
            "experience": list((profile.experience if profile else []) or []),
            "projects": list((profile.projects if profile else []) or []),
            "education": list((profile.education if profile else []) or []),
            "preferences": prefs,
        },
        "master_resume_text": (profile.master_resume_text if profile else "") or "",
        "current_job": {
            "id": str(job.id),
            "title": job.title,
            "company": job.company,
            "description": job.description,
            "url": job.url,
            "location": job.location,
        },
        "application_id": str(app.id),
        "status": "tailoring",
        "errors": [],
        "messages": [],
        "cover_letter_tone": tone,
        "approval_decision": None,
    }

    thread_id = f"app-{app.id}"
    copilot_graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": thread_id, "db": db}},
    )

    db.refresh(app)
    docs = db.scalars(
        select(Document)
        .where(Document.application_id == app.id)
        .order_by(Document.type.asc(), desc(Document.version))
    ).all()
    return _serialize_detail(user, app, job, docs)


@router.get("", response_model=list[ApplicationSummaryResponse])
def list_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ApplicationSummaryResponse]:
    """List all applications for the current user."""
    apps = db.scalars(
        select(Application)
        .where(Application.user_id == user.id)
        .order_by(desc(Application.updated_at))
    ).all()
    results: list[ApplicationSummaryResponse] = []
    for app in apps:
        job = db.get(Job, app.job_id)
        if job is None:
            continue
        results.append(
            ApplicationSummaryResponse(
                id=app.id,
                job_id=app.job_id,
                status=app.status,
                job_title=job.title,
                company=job.company,
                location=job.location,
                fit_score=job.fit_score,
                job_url=job.url,
                applied_at=app.applied_at,
                updated_at=app.updated_at,
                notes=app.notes or "",
            )
        )
    return results


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
def get_application_detail(
    application_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailResponse:
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    docs = db.scalars(
        select(Document)
        .where(Document.application_id == app.id)
        .order_by(Document.type.asc(), desc(Document.version))
    ).all()
    return _serialize_detail(user, app, job, docs)


@router.patch("/{application_id}/status", response_model=ApplicationSummaryResponse)
def update_application_status(
    application_id: uuid.UUID,
    payload: ApplicationStatusUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationSummaryResponse:
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    app.status = payload.status
    if payload.status == "applied" and app.applied_at is None:
        app.applied_at = datetime.now(timezone.utc)
    if payload.notes is not None:
        app.notes = payload.notes
    db.add(app)
    db.commit()
    db.refresh(app)

    job = db.get(Job, app.job_id)
    assert job is not None
    return ApplicationSummaryResponse(
        id=app.id,
        job_id=app.job_id,
        status=app.status,
        job_title=job.title,
        company=job.company,
        location=job.location,
        fit_score=job.fit_score,
        job_url=job.url,
        applied_at=app.applied_at,
        updated_at=app.updated_at,
        notes=app.notes or "",
    )


@router.put("/{application_id}/cover-letter", response_model=DocumentResponse)
def update_cover_letter(
    application_id: uuid.UUID,
    payload: CoverLetterUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Save user edits to the application's cover letter as a new version."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    max_ver = db.scalar(
        select(func.max(Document.version)).where(
            Document.application_id == app.id,
            Document.type == "cover_letter",
        )
    )
    next_version = (max_ver or 0) + 1
    doc = Document(
        user_id=user.id,
        application_id=app.id,
        type="cover_letter",
        content=payload.content,
        doc_metadata={"tone": payload.tone or "formal", "edited_by_user": True},
        version=next_version,
    )
    db.add(doc)
    db.flush()
    app.cover_letter_id = doc.id
    db.add(app)
    db.commit()
    db.refresh(doc)
    return _serialize_doc(doc)


@router.get("/{application_id}/resume/download")
def download_tailored_resume(
    application_id: uuid.UUID,
    format: str = Query(default="docx", pattern="^(docx|pdf|md)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the latest tailored resume in DOCX, PDF, or Markdown format."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    doc = None
    if app.resume_version_id:
        doc = db.get(Document, app.resume_version_id)
    if doc is None:
        doc = db.scalar(
            select(Document)
            .where(Document.application_id == app.id, Document.type == "resume")
            .order_by(desc(Document.version))
        )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tailored resume found.")

    if format == "md":
        return Response(
            content=doc.content.encode("utf-8"),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="tailored-resume-v{doc.version}.md"'},
        )

    if format == "pdf":
        pdf_bytes = render_resume_pdf(doc.content)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="tailored-resume-v{doc.version}.pdf"'},
        )

    structured = (doc.doc_metadata or {}).get("structured")
    if structured:
        tailored_obj = TailoredResumeOutput.model_validate(structured)
    else:
        tailored_obj = TailoredResumeOutput(summary=doc.content, keyword_coverage_score=0.0)
    docx_bytes = render_resume_docx(user, tailored_obj)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="tailored-resume-v{doc.version}.docx"'},
    )


@router.post("/{application_id}/approve", response_model=ApplicationDetailResponse)
def approve_application(
    application_id: uuid.UUID,
    payload: ApplicationApprovalRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailResponse:
    """Resume a paused LangGraph checkpoint after human approval."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    feedback = payload.feedback if payload else ""
    resumed = resume_application_approval(
        thread_id=f"app-{app.id}",
        decision="approved",
        feedback=feedback,
        db=db,
    )
    if resumed is None:
        app.status = "ready_to_submit"
        if feedback:
            app.notes = f"{app.notes}\n[approved] {feedback}".strip() if app.notes else f"[approved] {feedback}"
        db.add(app)
        db.commit()

    return get_application_detail(application_id, user=user, db=db)


@router.post("/{application_id}/form-fill", response_model=FormFillReport)
def run_form_filler(
    application_id: uuid.UUID,
    payload: FormFillRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormFillReport:
    """Run Playwright FormFillerAgent for an application and STOP before submission."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    _, report = FormFillerAgent().run(
        db,
        user,
        app,
        job,
        target_url=payload.url if payload else None,
        headless=payload.headless if payload else True,
    )
    return report


@router.get("/{application_id}/screenshots/{filename}")
def get_application_screenshot(
    application_id: uuid.UUID,
    filename: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve a Playwright review screenshot safely."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    safe_name = Path(filename).name
    target = (ARTIFACTS_ROOT / str(application_id) / safe_name).resolve()
    app_dir = (ARTIFACTS_ROOT / str(application_id)).resolve()
    if not str(target).startswith(str(app_dir)) or not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found.")
    return FileResponse(target, media_type="image/png")


@router.post("/{application_id}/follow-up", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def draft_follow_up_email(
    application_id: uuid.UUID,
    payload: FollowUpRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Draft a follow-up email pending human approval (never auto-sent)."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    doc = FollowUpAgent().draft_followup(
        db,
        user,
        app,
        job,
        followup_type=payload.followup_type,
        to_email=payload.to_email,
        extra_context=payload.extra_context,
    )
    return _serialize_doc(doc)


@router.post("/{application_id}/follow-up/{doc_id}/approve-draft", response_model=DocumentResponse)
def approve_and_save_follow_up_draft(
    application_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: FollowUpApproveRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Approve a follow-up email draft and save it as a Gmail Draft (never auto-sent)."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    doc = db.get(Document, doc_id)
    if doc is None or doc.application_id != app.id or doc.type != "email_draft":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email draft not found.")

    try:
        updated = FollowUpAgent().approve_and_save_gmail_draft(
            db,
            user,
            doc,
            to_email=payload.to_email if payload else None,
            subject=payload.subject if payload else None,
            body=payload.body if payload else None,
        )
    except GmailServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_doc(updated)


@router.post("/{application_id}/interview-prep", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def generate_interview_prep(
    application_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Run InterviewPrepAgent to generate questions, STAR outlines, and company notes."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    doc = InterviewPrepAgent().run(db, user, app, job)
    return _serialize_doc(doc)


@router.post("/{application_id}/reject", response_model=ApplicationDetailResponse)
def reject_application(
    application_id: uuid.UUID,
    payload: ApplicationApprovalRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationDetailResponse:
    """Reject or cancel a paused LangGraph checkpoint."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    feedback = payload.feedback if payload else ""
    resumed = resume_application_approval(
        thread_id=f"app-{app.id}",
        decision="rejected",
        feedback=feedback,
        db=db,
    )
    if resumed is None:
        app.status = "rejected"
        if feedback:
            app.notes = f"{app.notes}\n[rejected] {feedback}".strip() if app.notes else f"[rejected] {feedback}"
        db.add(app)
        db.commit()

    return get_application_detail(application_id, user=user, db=db)


@router.post("/{application_id}/form-fill", response_model=FormFillReport)
def run_form_filler(
    application_id: uuid.UUID,
    payload: FormFillRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FormFillReport:
    """Run Playwright FormFillerAgent for an application and STOP before submission."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    _, report = FormFillerAgent().run(
        db,
        user,
        app,
        job,
        target_url=payload.url if payload else None,
        headless=payload.headless if payload else True,
    )
    return report


@router.get("/{application_id}/screenshots/{filename}")
def get_application_screenshot(
    application_id: uuid.UUID,
    filename: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve a Playwright review screenshot safely."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")

    safe_name = Path(filename).name
    target = (ARTIFACTS_ROOT / str(application_id) / safe_name).resolve()
    app_dir = (ARTIFACTS_ROOT / str(application_id)).resolve()
    if not str(target).startswith(str(app_dir)) or not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found.")
    return FileResponse(target, media_type="image/png")


@router.post("/{application_id}/follow-up", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def draft_follow_up_email(
    application_id: uuid.UUID,
    payload: FollowUpRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Draft a follow-up email pending human approval (never auto-sent)."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    doc = FollowUpAgent().draft_followup(
        db,
        user,
        app,
        job,
        followup_type=payload.followup_type,
        to_email=payload.to_email,
        extra_context=payload.extra_context,
    )
    return _serialize_doc(doc)


@router.post("/{application_id}/follow-up/{doc_id}/approve-draft", response_model=DocumentResponse)
def approve_and_save_follow_up_draft(
    application_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: FollowUpApproveRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Approve a follow-up email draft and save it as a Gmail Draft (never auto-sent)."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    doc = db.get(Document, doc_id)
    if doc is None or doc.application_id != app.id or doc.type != "email_draft":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email draft not found.")

    try:
        updated = FollowUpAgent().approve_and_save_gmail_draft(
            db,
            user,
            doc,
            to_email=payload.to_email if payload else None,
            subject=payload.subject if payload else None,
            body=payload.body if payload else None,
        )
    except GmailServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_doc(updated)


@router.post("/{application_id}/interview-prep", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def generate_interview_prep(
    application_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Run InterviewPrepAgent to generate questions, STAR outlines, and company notes."""
    app = db.get(Application, application_id)
    if app is None or app.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    job = db.get(Job, app.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated job not found.")

    doc = InterviewPrepAgent().run(db, user, app, job)
    return _serialize_doc(doc)
