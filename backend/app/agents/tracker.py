from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import record_agent_run
from app.agents.prompts import load_prompt
from app.models.application import Application
from app.models.job import Job
from app.models.telemetry import Email
from app.models.user import User
from app.schemas.phase4 import EmailClassificationOutput, TrackerSyncMessage
from app.services.gmail import GmailService
from app.services.groq import GroqService, GroqServiceError

logger = logging.getLogger(__name__)


class TrackerAgent:
    """Reads recent Gmail messages, classifies application updates, and updates statuses."""

    name = "TrackerAgent"

    def __init__(
        self,
        groq_service: GroqService | None = None,
        gmail_service: GmailService | None = None,
    ) -> None:
        self.groq = groq_service or GroqService()
        self.gmail = gmail_service or GmailService()

    def _classify_message(
        self,
        subject: str,
        snippet: str,
        company_names: list[str],
    ) -> tuple[EmailClassificationOutput, int | None]:
        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("tracker", "v1")
                user_prompt = (
                    f"Known Applied Companies: {', '.join(company_names) or 'None'}\n"
                    f"Subject: {subject}\n"
                    f"Snippet: {snippet[:1500]}"
                )
                res = self.groq.complete_json(
                    system_prompt, user_prompt, EmailClassificationOutput, temperature=0.0, max_tokens=256
                )
                return res.data, res.tokens_used
            except GroqServiceError as exc:
                logger.warning("Groq email classification failed, using rules: %s", exc)

        haystack = f"{subject} {snippet}".lower()
        classification = "other"
        if any(k in haystack for k in ("offer", "compensation package", "extend an offer")):
            classification = "offer"
        elif any(k in haystack for k in ("interview", "schedule a call", "technical screen", "assessment")):
            classification = "interview"
        elif any(k in haystack for k in ("unfortunately", "not moving forward", "other candidates", "regret to inform")):
            classification = "rejected"
        elif any(k in haystack for k in ("application received", "thank you for applying", "applied to")):
            classification = "applied"

        matched = ""
        for comp in company_names:
            if comp and comp.lower() in haystack:
                matched = comp
                break

        return (
            EmailClassificationOutput(
                classification=classification,  # type: ignore[arg-type]
                matched_company=matched,
                confidence=0.75,
                summary=subject[:120],
            ),
            None,
        )

    def run(
        self,
        db: Session,
        user: User,
        *,
        max_results: int = 20,
        query: str = "",
        simulated_messages: list[TrackerSyncMessage] | None = None,
    ) -> dict[str, object]:
        started = time.perf_counter()

        if simulated_messages is not None:
            raw_messages = [m.model_dump() for m in simulated_messages]
        else:
            raw_messages = self.gmail.list_recent_messages(
                user, db, max_results=max_results, query=query
            )

        apps = db.scalars(select(Application).where(Application.user_id == user.id)).all()
        app_by_company: dict[str, Application] = {}
        for app in apps:
            job = db.get(Job, app.job_id)
            if job and job.company:
                app_by_company[job.company.lower()] = app

        company_names = list(app_by_company.keys())
        existing_ids = set(
            db.scalars(select(Email.gmail_message_id).where(Email.user_id == user.id)).all()
        )

        saved_emails: list[Email] = []
        updated_apps = 0
        total_tokens = 0
        has_tokens = False

        for msg in raw_messages:
            msg_id = str(msg.get("gmail_message_id", ""))
            if not msg_id or msg_id in existing_ids:
                continue
            existing_ids.add(msg_id)

            subject = str(msg.get("subject", ""))
            snippet = str(msg.get("snippet", ""))
            result, tokens = self._classify_message(subject, snippet, company_names)
            if tokens is not None:
                total_tokens += tokens
                has_tokens = True

            matched_app: Application | None = None
            if result.matched_company:
                matched_app = app_by_company.get(result.matched_company.lower())
            if matched_app is None:
                haystack = f"{subject} {snippet} {msg.get('from_email', '')}".lower()
                for comp_lower, app in app_by_company.items():
                    if comp_lower in haystack:
                        matched_app = app
                        break

            email_row = Email(
                user_id=user.id,
                gmail_message_id=msg_id,
                application_id=matched_app.id if matched_app else None,
                classification=result.classification,
                subject=subject[:500],
                snippet=snippet[:2000],
                received_at=datetime.now(timezone.utc),
            )
            db.add(email_row)
            saved_emails.append(email_row)

            if matched_app and result.classification in {"applied", "interview", "rejected", "offer"}:
                if matched_app.status != result.classification:
                    matched_app.status = result.classification
                    note_line = f"[TrackerAgent] Classified email '{subject[:80]}' -> {result.classification}"
                    matched_app.notes = (
                        f"{matched_app.notes}\n{note_line}".strip()
                        if matched_app.notes
                        else note_line
                    )
                    if result.classification == "applied" and matched_app.applied_at is None:
                        matched_app.applied_at = datetime.now(timezone.utc)
                    db.add(matched_app)
                    updated_apps += 1

        db.commit()
        for em in saved_emails:
            db.refresh(em)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"fetched={len(raw_messages)}, query='{query}'",
            output_summary=f"new_emails={len(saved_emails)}, updated_apps={updated_apps}",
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=total_tokens if has_tokens else None,
        )

        return {
            "synced_count": len(saved_emails),
            "updated_applications": updated_apps,
            "emails": saved_emails,
        }
