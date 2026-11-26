from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.agents.base import record_agent_run
from app.agents.prompts import load_prompt
from app.agents.resume_tailor import render_resume_pdf
from app.models.application import Application, Document
from app.models.job import Job
from app.models.user import User
from app.schemas.phase4 import FormFillReport, FreeTextAnswersOutput
from app.services.groq import GroqService, GroqServiceError
from app.services.playwright import PlaywrightFormService

logger = logging.getLogger(__name__)


class FormFillerAgent:
    """Fills job application forms via Playwright, attaches tailored resume, and STOPS before submit."""

    name = "FormFillerAgent"

    def __init__(
        self,
        groq_service: GroqService | None = None,
        playwright_service: PlaywrightFormService | None = None,
    ) -> None:
        self.groq = groq_service or GroqService()
        self.playwright = playwright_service or PlaywrightFormService()

    def _generate_free_text_answers(
        self,
        *,
        questions: list[str],
        user: User,
        job: Job,
    ) -> tuple[dict[str, str], int | None]:
        if not questions:
            return {}, None

        profile = user.profile
        skills = list((profile.skills if profile else []) or [])
        experience = list((profile.experience if profile else []) or [])
        projects = list((profile.projects if profile else []) or [])

        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("form_filler", "v1")
                user_prompt = (
                    f"Target Role: {job.title} at {job.company}\n"
                    f"Job Description:\n{job.description[:2500]}\n\n"
                    f"Candidate Skills: {skills}\n"
                    f"Experience: {experience}\n"
                    f"Projects: {projects}\n\n"
                    f"Questions to answer:\n" + "\n".join(f"- {q}" for q in questions)
                )
                res = self.groq.complete_json(
                    system_prompt, user_prompt, FreeTextAnswersOutput, temperature=0.2, max_tokens=1024
                )
                return {item.question: item.answer for item in res.data.answers}, res.tokens_used
            except GroqServiceError as exc:
                logger.warning("Groq form answer generation failed, using fallback: %s", exc)

        # Truthful deterministic fallback
        top_skills = ", ".join(skills[:5]) or "software engineering"
        proj_name = projects[0].get("name") if projects else ""
        answers: dict[str, str] = {}
        for q in questions:
            base = (
                f"I am excited to apply for the {job.title} role at {job.company}. "
                f"My verified background includes {top_skills}"
            )
            if proj_name:
                base += f", including hands-on work on {proj_name}."
            else:
                base += "."
            answers[q] = base
        return answers, None

    def run(
        self,
        db: Session,
        user: User,
        application: Application,
        job: Job,
        *,
        target_url: str | None = None,
        headless: bool = True,
    ) -> tuple[Document, FormFillReport]:
        started = time.perf_counter()
        url = (target_url or job.url).strip()

        profile = user.profile
        prefs = (profile.preferences if profile else {}) or {}
        experience = list((profile.experience if profile else []) or [])
        profile_data: dict[str, Any] = {
            "name": user.name,
            "email": user.email,
            "phone": prefs.get("phone", ""),
            "linkedin_url": prefs.get("linkedin_url", ""),
            "github_url": prefs.get("github_url", ""),
            "portfolio_url": prefs.get("portfolio_url", ""),
            "recent_company": experience[0].get("company", "") if experience else "",
            "recent_title": experience[0].get("title", "") if experience else "",
        }

        resume_doc = db.scalar(
            select(Document)
            .where(Document.application_id == application.id, Document.type == "resume")
            .order_by(desc(Document.version))
        )
        cover_doc = db.scalar(
            select(Document)
            .where(Document.application_id == application.id, Document.type == "cover_letter")
            .order_by(desc(Document.version))
        )
        cover_letter_text = cover_doc.content if cover_doc else ""

        tokens_holder: list[int | None] = [None]

        def _answer_cb(questions: list[str]) -> dict[str, str]:
            answers, tokens = self._generate_free_text_answers(
                questions=questions, user=user, job=job
            )
            tokens_holder[0] = tokens
            return answers

        with tempfile.TemporaryDirectory() as tmpdir:
            resume_path: Path | None = None
            if resume_doc and resume_doc.content:
                resume_path = Path(tmpdir) / f"tailored-resume-v{resume_doc.version}.pdf"
                resume_path.write_bytes(render_resume_pdf(resume_doc.content))

            report = self.playwright.fill_application_form(
                application_id=str(application.id),
                url=url,
                profile_data=profile_data,
                resume_file_path=resume_path,
                cover_letter_text=cover_letter_text,
                answer_generator=_answer_cb,
                headless=headless,
            )

        max_ver = db.scalar(
            select(func.max(Document.version)).where(
                Document.application_id == application.id,
                Document.type == "form_fill",
            )
        )
        next_version = (max_ver or 0) + 1

        doc = Document(
            user_id=user.id,
            application_id=application.id,
            type="form_fill",
            content=report.notes,
            doc_metadata=report.model_dump(),
            version=next_version,
        )
        db.add(doc)
        if report.status == "ready_for_review":
            application.status = "awaiting_approval"
            db.add(application)
        db.commit()
        db.refresh(doc)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"application={application.id}, url={url}",
            output_summary=f"status={report.status}, filled={len(report.filled_fields)}, unfilled={len(report.unfilled_fields)}",
            status="success" if report.status != "failed" else "failed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=tokens_holder[0],
            error=report.blocked_reason if report.status == "blocked" else (report.notes if report.status == "failed" else None),
        )
        return doc, report
