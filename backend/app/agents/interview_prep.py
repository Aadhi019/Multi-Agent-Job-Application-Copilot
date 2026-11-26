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
from app.schemas.phase5 import InterviewPrepOutput, StarOutline
from app.services.groq import GroqService, GroqServiceError

logger = logging.getLogger(__name__)


class InterviewPrepAgent:
    """Generates technical/behavioral questions, STAR outlines, company notes, and interviewer questions."""

    name = "InterviewPrepAgent"

    def __init__(self, groq_service: GroqService | None = None) -> None:
        self.groq = groq_service or GroqService()

    def _deterministic_prep(self, user: User, job: Job) -> InterviewPrepOutput:
        profile = user.profile
        skills = list((profile.skills if profile else []) or [])
        projects = list((profile.projects if profile else []) or [])
        experience = list((profile.experience if profile else []) or [])

        top_skills = skills[:4] or ["system architecture", "API design", "testing"]
        tech_questions = [
            f"How have you applied {top_skills[0]} in production to handle reliability and scale?",
            f"Walk through how you design and test services for a role like {job.title} at {job.company}.",
            f"What trade-offs did you consider when choosing {', '.join(top_skills[:2])}?",
            "How do you debug latency bottlenecks or data consistency issues across services?",
        ]
        behavioral_questions = [
            "Tell me about a technically ambiguous project you drove from design to delivery.",
            "Describe a time you had to resolve a critical production bug under time pressure.",
            "Tell me about a disagreement on architecture and how you aligned the team.",
        ]

        star_outlines: list[StarOutline] = []
        if projects:
            proj = projects[0]
            star_outlines.append(
                StarOutline(
                    question=behavioral_questions[0],
                    mapped_project_or_role=proj.get("name", "Verified Project"),
                    situation=f"While building {proj.get('name', 'the project')} ({proj.get('description', '')}).",
                    task=f"Needed to deliver a reliable solution relevant to {job.title} requirements.",
                    action=f"Implemented core architecture using {', '.join(proj.get('tech_stack', top_skills[:3]))}.",
                    result=(proj.get("highlights") or ["Delivered measurable improvements in reliability and workflow speed."])[0],
                )
            )
        if experience:
            exp = experience[0]
            star_outlines.append(
                StarOutline(
                    question=behavioral_questions[1],
                    mapped_project_or_role=f"{exp.get('title', '')} @ {exp.get('company', '')}".strip(" @"),
                    situation=f"During tenure as {exp.get('title', 'Engineer')} at {exp.get('company', 'previous company')}.",
                    task="Maintained production quality and met delivery milestones.",
                    action=(exp.get("highlights") or ["Designed, tested, and shipped backend improvements."])[0],
                    result="Improved system stability and team delivery velocity.",
                )
            )
        if not star_outlines:
            star_outlines.append(
                StarOutline(
                    question=behavioral_questions[0],
                    mapped_project_or_role="Master Resume Experience",
                    situation=f"Applying verified background in {', '.join(top_skills)}.",
                    task=f"Solve core engineering requirements highlighted by {job.company}.",
                    action="Applied structured testing, modular design, and iterative validation.",
                    result="Delivered maintainable, production-ready outcomes.",
                )
            )

        company_notes = [
            f"Target role: {job.title} at {job.company} ({job.location or 'Unspecified location'}).",
            f"Key JD focus: {job.description[:220].strip()}...",
            "Highlight overlap between your verified skills and the role's primary technical stack.",
        ]
        questions_to_ask = [
            f"What does success look like in the first 90 days for the {job.title} role at {job.company}?",
            "What are the biggest technical scaling or reliability challenges the team is tackling right now?",
            "How does the team balance shipping new features with code quality and testing?",
            "How is engineering work scoped and reviewed across the team?",
        ]

        return InterviewPrepOutput(
            technical_questions=tech_questions,
            behavioral_questions=behavioral_questions,
            star_outlines=star_outlines,
            company_research_notes=company_notes,
            questions_to_ask=questions_to_ask,
        )

    def run(self, db: Session, user: User, application: Application, job: Job) -> Document:
        started = time.perf_counter()
        profile = user.profile
        tokens_used: int | None = None
        mode = "deterministic"

        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("interview_prep", "v1")
                user_prompt = (
                    f"Role: {job.title} at {job.company} ({job.location})\n"
                    f"Job Description:\n{job.description[:3500]}\n\n"
                    f"Candidate Skills: {profile.skills if profile else []}\n"
                    f"Experience: {profile.experience if profile else []}\n"
                    f"Projects: {profile.projects if profile else []}\n"
                    f"Master Resume:\n{(profile.master_resume_text if profile else '')[:3500]}"
                )
                res = self.groq.complete_json(
                    system_prompt, user_prompt, InterviewPrepOutput, temperature=0.25, max_tokens=2500
                )
                prep = res.data
                tokens_used = res.tokens_used
                mode = "groq"
            except GroqServiceError as exc:
                logger.warning("Groq interview prep failed, using deterministic fallback: %s", exc)
                prep = self._deterministic_prep(user, job)
        else:
            prep = self._deterministic_prep(user, job)

        lines = [
            f"# Interview Prep — {job.title} at {job.company}",
            "",
            "## Technical Questions",
            *[f"- {q}" for q in prep.technical_questions],
            "",
            "## Behavioral Questions",
            *[f"- {q}" for q in prep.behavioral_questions],
            "",
            "## STAR Answer Outlines",
        ]
        for s in prep.star_outlines:
            lines.extend(
                [
                    f"### {s.question} ({s.mapped_project_or_role})",
                    f"- **Situation:** {s.situation}",
                    f"- **Task:** {s.task}",
                    f"- **Action:** {s.action}",
                    f"- **Result:** {s.result}",
                    "",
                ]
            )
        lines.extend(["## Company Research Notes", *[f"- {n}" for n in prep.company_research_notes], ""])
        lines.extend(["## Questions to Ask", *[f"- {q}" for q in prep.questions_to_ask]])

        max_ver = db.scalar(
            select(func.max(Document.version)).where(
                Document.application_id == application.id,
                Document.type == "prep",
            )
        )
        next_version = (max_ver or 0) + 1

        doc = Document(
            user_id=user.id,
            application_id=application.id,
            type="prep",
            content="\n".join(lines),
            doc_metadata={"mode": mode, "structured": prep.model_dump()},
            version=next_version,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"application={application.id}, role='{job.title}' @ '{job.company}'",
            output_summary=f"prep_v{next_version}: {len(prep.technical_questions)} tech, {len(prep.star_outlines)} STAR outlines",
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=tokens_used,
        )
        return doc
