from __future__ import annotations

import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.base import record_agent_run
from app.agents.prompts import load_prompt
from app.models.application import Application, Document
from app.models.job import Job
from app.models.user import User
from app.schemas.phase4 import FollowUpLLMOutput
from app.services.gmail import GmailService
from app.services.groq import GroqService, GroqServiceError

logger = logging.getLogger(__name__)


class FollowUpAgent:
    """Drafts follow-up emails and saves them as Gmail drafts ONLY after human approval."""

    name = "FollowUpAgent"

    def __init__(
        self,
        groq_service: GroqService | None = None,
        gmail_service: GmailService | None = None,
    ) -> None:
        self.groq = groq_service or GroqService()
        self.gmail = gmail_service or GmailService()

    def _deterministic_draft(self, user: User, job: Job, followup_type: str) -> FollowUpLLMOutput:
        if followup_type == "thank_you":
            subject = f"Thank you — {job.title} conversation with {job.company}"
            body = (
                f"Dear {job.company} Team,\n\n"
                f"Thank you for taking the time to speak with me regarding the {job.title} role. "
                f"I enjoyed learning more about your engineering priorities and remain very enthusiastic about contributing.\n\n"
                f"Best regards,\n{user.name}"
            )
            window = "Within 24 hours of interview"
        elif followup_type == "after_interview":
            subject = f"Following up — {job.title} interview at {job.company}"
            body = (
                f"Dear {job.company} Hiring Team,\n\n"
                f"I hope your week is going well. I wanted to follow up after our recent interview for the {job.title} position "
                f"and reiterate my strong interest in joining {job.company}.\n\n"
                f"Please let me know if any additional information would be helpful.\n\n"
                f"Best regards,\n{user.name}"
            )
            window = "3-5 business days after interview"
        else:
            subject = f"Application Follow-Up: {job.title} — {user.name}"
            body = (
                f"Dear {job.company} Recruiting Team,\n\n"
                f"I recently submitted my application for the {job.title} role and wanted to briefly express my continued enthusiasm. "
                f"With my background in {', '.join((user.profile.skills if user.profile else [])[:4]) or 'software engineering'}, "
                f"I would welcome the opportunity to discuss how I can contribute to your team.\n\n"
                f"Best regards,\n{user.name}"
            )
            window = "5-7 days after applying"

        return FollowUpLLMOutput(subject=subject, body=body, recommended_send_window=window)

    def draft_followup(
        self,
        db: Session,
        user: User,
        application: Application,
        job: Job,
        *,
        followup_type: str = "after_applying",
        to_email: str = "",
        extra_context: str = "",
    ) -> Document:
        started = time.perf_counter()
        tokens_used: int | None = None
        mode = "deterministic"

        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("follow_up", "v1")
                user_prompt = (
                    f"Follow-up Type: {followup_type}\n"
                    f"Role: {job.title} at {job.company}\n"
                    f"Candidate Name: {user.name}\n"
                    f"Candidate Skills: {(user.profile.skills if user.profile else [])}\n"
                    f"Additional Context: {extra_context or 'None'}\n"
                )
                res = self.groq.complete_json(
                    system_prompt, user_prompt, FollowUpLLMOutput, temperature=0.3, max_tokens=1024
                )
                draft_out = res.data
                tokens_used = res.tokens_used
                mode = "groq"
            except GroqServiceError as exc:
                logger.warning("Groq follow-up draft failed, using fallback: %s", exc)
                draft_out = self._deterministic_draft(user, job, followup_type)
        else:
            draft_out = self._deterministic_draft(user, job, followup_type)

        max_ver = db.scalar(
            select(func.max(Document.version)).where(
                Document.application_id == application.id,
                Document.type == "email_draft",
            )
        )
        next_version = (max_ver or 0) + 1

        doc = Document(
            user_id=user.id,
            application_id=application.id,
            type="email_draft",
            content=draft_out.body,
            doc_metadata={
                "status": "pending_approval",
                "followup_type": followup_type,
                "to_email": to_email,
                "subject": draft_out.subject,
                "recommended_send_window": draft_out.recommended_send_window,
                "gmail_draft_id": None,
                "mode": mode,
            },
            version=next_version,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"application={application.id}, type={followup_type}",
            output_summary=f"draft_v{next_version} pending approval (mode={mode})",
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=tokens_used,
        )
        return doc

    def approve_and_save_gmail_draft(
        self,
        db: Session,
        user: User,
        doc: Document,
        *,
        to_email: str | None = None,
        subject: str | None = None,
        body: str | None = None,
    ) -> Document:
        """Save approved draft into Gmail Drafts (NEVER sends automatically)."""
        meta = dict(doc.doc_metadata or {})
        eff_to = to_email if to_email is not None else str(meta.get("to_email", ""))
        eff_subject = subject if subject is not None else str(meta.get("subject", "Application Follow-Up"))
        eff_body = body if body is not None else doc.content

        doc.content = eff_body
        meta["to_email"] = eff_to
        meta["subject"] = eff_subject

        if user.gmail_credentials_encrypted:
            draft_res = self.gmail.create_draft(
                user,
                db,
                to=eff_to,
                subject=eff_subject,
                body=eff_body,
            )
            meta["gmail_draft_id"] = draft_res.get("draft_id")
            meta["status"] = "saved_to_gmail"
        else:
            meta["status"] = "approved_local_only"

        doc.doc_metadata = meta
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc
