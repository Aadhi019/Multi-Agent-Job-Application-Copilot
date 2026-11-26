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
from app.schemas.application import CoverLetterOutput
from app.services.groq import GroqService, GroqServiceError

logger = logging.getLogger(__name__)


def _format_cover_letter(output: CoverLetterOutput, candidate_name: str) -> str:
    body = "\n\n".join(output.paragraphs)
    return f"{output.greeting}\n\n{body}\n\n{output.closing}\n{candidate_name}".strip()


class CoverLetterAgent:
    """Generates a personalized, editable 3-4 paragraph cover letter."""

    name = "CoverLetterAgent"

    def __init__(self, groq_service: GroqService | None = None) -> None:
        self.groq = groq_service or GroqService()

    def _deterministic_letter(self, user: User, job: Job, tone: str) -> CoverLetterOutput:
        profile = user.profile
        skills = list((profile.skills if profile else []) or [])
        projects = list((profile.projects if profile else []) or [])
        experience = list((profile.experience if profile else []) or [])

        top_skills = ", ".join(skills[:5]) if skills else "software engineering and problem solving"
        highlight_project = projects[0].get("name") if projects else ""
        recent_role = (
            f"{experience[0].get('title', '')} at {experience[0].get('company', '')}".strip(" at")
            if experience
            else ""
        )

        if tone == "friendly":
            greeting = f"Hi {job.company} Hiring Team,"
            p1 = f"I'm excited to apply for the {job.title} role at {job.company}. Your team's focus strongly aligns with my hands-on background in {top_skills}."
            closing = "Warm regards,"
        elif tone == "concise":
            greeting = f"Dear {job.company} Team,"
            p1 = f"I am applying for the {job.title} position at {job.company}, bringing verified experience in {top_skills}."
            closing = "Best regards,"
        else:
            greeting = f"Dear {job.company} Hiring Committee,"
            p1 = f"I am writing to express my interest in the {job.title} role at {job.company}. My background in {top_skills} positions me to contribute immediately to your engineering goals."
            closing = "Sincerely,"

        p2_parts = []
        if recent_role:
            p2_parts.append(f"Most recently, I served as {recent_role}, delivering reliable production systems.")
        if highlight_project:
            p2_parts.append(f"In my project {highlight_project}, I applied practical architecture and testing practices end-to-end.")
        if not p2_parts:
            p2_parts.append(f"Across my work, I have consistently delivered maintainable software using {top_skills}.")
        p2 = " ".join(p2_parts)

        p3 = f"Thank you for considering my application for {job.title}. I would welcome the opportunity to discuss how my verified experience can support {job.company}."

        return CoverLetterOutput(
            subject=f"Application for {job.title} — {user.name}",
            greeting=greeting,
            paragraphs=[p1, p2, p3],
            closing=closing,
            key_points_used=[s for s in skills[:4]],
        )

    def run(
        self,
        db: Session,
        user: User,
        application: Application,
        job: Job,
        *,
        tone: str | None = None,
    ) -> Document:
        started = time.perf_counter()
        profile = user.profile
        prefs = (profile.preferences if profile else {}) or {}
        eff_tone = tone or prefs.get("cover_letter_tone", "formal")
        if eff_tone not in {"formal", "friendly", "concise"}:
            eff_tone = "formal"

        tokens_used: int | None = None
        mode = "deterministic"

        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("cover_letter", "v1")
                user_prompt = (
                    f"Requested Tone: {eff_tone}\n"
                    f"Target Role: {job.title} at {job.company} ({job.location})\n"
                    f"Job Description:\n{job.description[:3500]}\n\n"
                    f"Candidate Name: {user.name}\n"
                    f"Verified Skills: {profile.skills if profile else []}\n"
                    f"Experience: {profile.experience if profile else []}\n"
                    f"Projects: {profile.projects if profile else []}\n"
                    f"Master Resume:\n{(profile.master_resume_text if profile else '')[:3500]}"
                )
                res = self.groq.complete_json(
                    system_prompt, user_prompt, CoverLetterOutput, temperature=0.3, max_tokens=1536
                )
                output = res.data
                tokens_used = res.tokens_used
                mode = "groq"
            except GroqServiceError as exc:
                logger.warning("Groq cover letter generation failed, using deterministic: %s", exc)
                output = self._deterministic_letter(user, job, eff_tone)
        else:
            output = self._deterministic_letter(user, job, eff_tone)

        rendered_text = _format_cover_letter(output, user.name)
        max_ver = db.scalar(
            select(func.max(Document.version)).where(
                Document.application_id == application.id,
                Document.type == "cover_letter",
            )
        )
        next_version = (max_ver or 0) + 1

        doc = Document(
            user_id=user.id,
            application_id=application.id,
            type="cover_letter",
            content=rendered_text,
            doc_metadata={
                "tone": eff_tone,
                "mode": mode,
                "subject": output.subject,
                "greeting": output.greeting,
                "paragraphs": output.paragraphs,
                "closing": output.closing,
                "key_points_used": output.key_points_used,
            },
            version=next_version,
        )
        db.add(doc)
        db.flush()

        application.cover_letter_id = doc.id
        db.add(application)
        db.commit()
        db.refresh(doc)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"application={application.id}, tone={eff_tone}, job='{job.title}'",
            output_summary=f"version={next_version}, length={len(rendered_text)} chars, mode={mode}",
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=tokens_used,
        )
        return doc
