from __future__ import annotations

import io
import logging
import re
import time
import uuid
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from docx import Document as DocxDocument
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.base import record_agent_run
from app.agents.prompts import load_prompt
from app.models.application import Application, Document
from app.models.evidence import ProfileFact, ResumeBullet
from app.models.job import Job
from app.models.user import User
from app.schemas.application import (
    TailoredExperienceEntry,
    TailoredProjectEntry,
    TailoredResumeOutput,
)
from app.schemas.evidence import (
    BulletVerificationItem,
    JDAnalysisOutput,
    JDRequirementItem,
    ResumeVerifierOutput,
    ResumeWriterOutput,
    VerificationReport,
    WrittenBulletItem,
)
from app.services.facts_extractor import get_facts_vector_store, list_profile_facts, rebuild_profile_facts
from app.services.groq import GroqService, GroqServiceError
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "with", "that", "this", "from", "have", "will", "your", "team", "work", "experience",
    "years", "ability", "strong", "using", "build", "building", "role", "looking", "about",
    "skills", "required", "preferred", "including", "such", "their", "they", "more", "than",
    "and", "for", "the", "are", "you", "our", "who", "into", "across", "must", "good",
}

_COMMON_ACTION_CAPS = {
    "Built", "Designed", "Led", "Created", "Developed", "Implemented", "Architected",
    "Reduced", "Improved", "Managed", "Delivered", "Automated", "Configured", "Engineered",
    "Integrated", "Scaled", "Optimized", "Maintained", "Deployed", "Tested", "Analyzed",
    "Collaborated", "Spearheaded", "Orchestrated", "Streamlined", "Refactored", "Verified",
    "Experience", "Project", "Skills", "Summary", "Education", "API", "APIs", "REST", "CI", "CD",
}


def _extract_jd_keywords(job_description: str, limit: int = 18) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", job_description or "")
    counts: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for tok in tokens:
        low = tok.lower().strip(".,")
        if low in _STOPWORDS or len(low) < 3:
            continue
        counts[low] = counts.get(low, 0) + 1
        if low not in canonical or tok[0].isupper():
            canonical[low] = tok.strip(".,")
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [canonical[k] for k, _ in ranked[:limit]]


def _ats_contact_line(user: User) -> str:
    prefs = (user.profile.preferences if user.profile else {}) or {}
    parts = [user.email]
    if prefs.get("phone"):
        parts.append(str(prefs["phone"]))
    locs = prefs.get("preferred_locations") or []
    if locs:
        parts.append(str(locs[0]))
    for key in ("linkedin_url", "github_url", "portfolio_url"):
        if prefs.get(key):
            parts.append(str(prefs[key]))
    return " | ".join(p.strip() for p in parts if p and str(p).strip())


def render_resume_markdown(user: User, tailored: TailoredResumeOutput) -> str:
    lines = [f"# {user.name}", _ats_contact_line(user), "", "## PROFESSIONAL SUMMARY", tailored.summary, ""]

    if tailored.skills_highlighted:
        lines.extend(["## TECHNICAL SKILLS", ", ".join(tailored.skills_highlighted), ""])

    if tailored.experience:
        lines.append("## WORK EXPERIENCE")
        for exp in tailored.experience:
            dates = " - ".join(p for p in [exp.start_date, exp.end_date] if p)
            meta = " | ".join(p for p in [exp.company, exp.location, dates] if p)
            header = f"### {exp.title}" + (f" | {meta}" if meta else "")
            lines.append(header)
            for bullet in exp.highlights:
                lines.append(f"- {bullet}")
            lines.append("")

    if tailored.projects:
        lines.append("## PROJECTS")
        for proj in tailored.projects:
            tech = f" | {', '.join(proj.tech_stack)}" if proj.tech_stack else ""
            lines.append(f"### {proj.name}{tech}")
            if proj.description:
                lines.append(proj.description)
            for bullet in proj.highlights:
                lines.append(f"- {bullet}")
            lines.append("")

    if tailored.education:
        lines.append("## EDUCATION")
        for edu in tailored.education:
            inst = edu.get("institution", "")
            deg = edu.get("degree", "")
            yr = edu.get("graduation_year", "")
            gpa = f"GPA: {edu['gpa']}" if edu.get("gpa") else ""
            lines.append("- " + " | ".join(p for p in [inst, deg, yr, gpa] if p))
        lines.append("")

    return "\n".join(lines).strip()


def render_resume_docx(user: User, tailored: TailoredResumeOutput) -> bytes:
    doc = DocxDocument()
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.65)
        section.right_margin = Inches(0.65)

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(10.5)
    normal_style.font.color.rgb = RGBColor(0x18, 0x18, 0x1B)

    name_p = doc.add_paragraph()
    name_run = name_p.add_run(user.name)
    name_run.bold = True
    name_run.font.size = Pt(16)
    name_p.paragraph_format.space_after = Pt(2)

    contact_p = doc.add_paragraph(_ats_contact_line(user))
    contact_p.paragraph_format.space_after = Pt(8)

    def _add_ats_heading(title: str) -> None:
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(8)
        h.paragraph_format.space_after = Pt(3)
        r = h.add_run(title.upper())
        r.bold = True
        r.font.size = Pt(11)

    _add_ats_heading("Professional Summary")
    doc.add_paragraph(tailored.summary)

    if tailored.skills_highlighted:
        _add_ats_heading("Technical Skills")
        doc.add_paragraph(", ".join(tailored.skills_highlighted))

    if tailored.experience:
        _add_ats_heading("Work Experience")
        for exp in tailored.experience:
            dates = " - ".join(p for p in [exp.start_date, exp.end_date] if p)
            meta = " | ".join(p for p in [exp.company, exp.location, dates] if p)
            role_p = doc.add_paragraph()
            role_p.paragraph_format.space_before = Pt(4)
            role_p.paragraph_format.space_after = Pt(2)
            role_run = role_p.add_run(f"{exp.title}" + (f" | {meta}" if meta else ""))
            role_run.bold = True
            for bullet in exp.highlights:
                bp = doc.add_paragraph(bullet, style="List Bullet")
                bp.paragraph_format.space_after = Pt(2)

    if tailored.projects:
        _add_ats_heading("Projects")
        for proj in tailored.projects:
            proj_p = doc.add_paragraph()
            proj_p.paragraph_format.space_before = Pt(4)
            proj_p.paragraph_format.space_after = Pt(2)
            tech = f" | {', '.join(proj.tech_stack)}" if proj.tech_stack else ""
            pr = proj_p.add_run(f"{proj.name}{tech}")
            pr.bold = True
            if proj.description:
                doc.add_paragraph(proj.description)
            for bullet in proj.highlights:
                bp = doc.add_paragraph(bullet, style="List Bullet")
                bp.paragraph_format.space_after = Pt(2)

    if tailored.education:
        _add_ats_heading("Education")
        for edu in tailored.education:
            parts = [edu.get("institution", ""), edu.get("degree", ""), edu.get("graduation_year", "")]
            if edu.get("gpa"):
                parts.append(f"GPA: {edu['gpa']}")
            doc.add_paragraph(" | ".join(p for p in parts if p))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


_PDF_CHAR_REPLACEMENTS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
        "\u200b": "",
        "\ufeff": "",
    }
)


def _sanitize_pdf_text(text: str) -> str:
    """Normalize unsupported Unicode punctuation for ReportLab Helvetica and XML-escape."""
    normalized = text.translate(_PDF_CHAR_REPLACEMENTS)
    latin1_safe = normalized.encode("latin-1", errors="replace").decode("latin-1")
    return xml_escape(latin1_safe)


def render_resume_pdf(markdown_text: str) -> bytes:
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=44,
        rightMargin=44,
        topMargin=40,
        bottomMargin=40,
    )
    base_styles = getSampleStyleSheet()
    name_style = ParagraphStyle(
        "ATSName",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
        spaceAfter=2,
    )
    contact_style = ParagraphStyle(
        "ATSContact",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "ATSSection",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#111827"),
        spaceBefore=8,
        spaceAfter=3,
    )
    role_style = ParagraphStyle(
        "ATSRole",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#111827"),
        spaceBefore=4,
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "ATSBody",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=3,
    )
    bullet_style = ParagraphStyle(
        "ATSBullet",
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-8,
        spaceAfter=2,
    )

    story = []
    seen_title = False
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 3))
        elif stripped.startswith("# "):
            seen_title = True
            story.append(Paragraph(_sanitize_pdf_text(stripped[2:]), name_style))
        elif seen_title and len(story) == 1 and not stripped.startswith("#"):
            story.append(Paragraph(_sanitize_pdf_text(stripped), contact_style))
        elif stripped.startswith("## "):
            story.append(Paragraph(_sanitize_pdf_text(stripped[3:].upper()), section_style))
            story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#D1D5DB"), spaceAfter=4))
        elif stripped.startswith("### "):
            story.append(Paragraph(_sanitize_pdf_text(stripped[4:]), role_style))
        elif stripped.startswith("- "):
            story.append(Paragraph(f"&#8226; {_sanitize_pdf_text(stripped[2:])}", bullet_style))
        else:
            story.append(Paragraph(_sanitize_pdf_text(stripped), body_style))

    pdf.build(story)
    return buf.getvalue()


def _strict_verify_bullet(
    bullet: WrittenBulletItem,
    fact_map: dict[str, ProfileFact],
    all_facts_corpus: str,
) -> tuple[str, str]:
    """Deterministic anti-hallucination check: cited facts must exist and no ungrounded numbers/tools."""
    cited = [fact_map[fid] for fid in bullet.fact_ids if fid in fact_map]
    if not cited:
        return "unsupported", "Bullet does not cite any valid profile fact ID."

    cited_corpus = " ".join(f"{f.text} {f.source_section}" for f in cited).lower()
    full_corpus = f"{cited_corpus} {all_facts_corpus}".lower()

    # Check quantitative numbers/percentages introduced in bullet that are absent from cited facts
    bullet_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", bullet.text))
    fact_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", cited_corpus))
    ungrounded_numbers = bullet_numbers - fact_numbers
    if ungrounded_numbers:
        return "unsupported", f"Introduces ungrounded metric(s): {', '.join(sorted(ungrounded_numbers))}."

    # Check proper/technical tokens (capitalized or containing +/#) not present anywhere in profile facts
    tech_tokens = re.findall(r"\b(?:[A-Z][A-Za-z0-9+#.-]{1,}|[a-z]+\+\+|[a-z]+#)\b", bullet.text)
    ungrounded_tokens = []
    for tok in tech_tokens:
        if tok in _COMMON_ACTION_CAPS:
            continue
        if tok.lower() not in full_corpus:
            ungrounded_tokens.append(tok)

    if ungrounded_tokens:
        return "unsupported", f"Introduces ungrounded term(s): {', '.join(ungrounded_tokens[:4])}."

    # Exact or near-exact match vs cited fact
    if any(f.text.lower().strip() == bullet.text.lower().strip() for f in cited):
        return "verified", "Exact match to cited profile fact."
    return "rephrased_ok", "Supported by cited profile fact(s)."


class ResumeTailorAgent:
    """4-stage evidence-backed resume tailoring pipeline with anti-hallucination verification."""

    name = "ResumeTailorAgent"

    def __init__(
        self,
        groq_service: GroqService | None = None,
        vector_store: VectorStoreService | None = None,
    ) -> None:
        self.groq = groq_service or GroqService()
        self.vector_store = vector_store

    def analyze_jd(self, job: Job) -> tuple[JDAnalysisOutput, int | None]:
        """Stage 1: Extract requirements, keywords, and seniority from JD."""
        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("jd_analyzer", "v1")
                user_prompt = f"Role: {job.title} at {job.company}\nLocation: {job.location}\n\nJD:\n{job.description[:4000]}"
                res = self.groq.complete_json(
                    system_prompt, user_prompt, JDAnalysisOutput, temperature=0.0, max_tokens=1024
                )
                return res.data, res.tokens_used
            except GroqServiceError as exc:
                logger.warning("JD analyzer Groq fallback: %s", exc)

        keywords = _extract_jd_keywords(f"{job.title} {job.description}", limit=14)
        reqs = [
            JDRequirementItem(requirement=kw, keywords=[kw], priority="required")
            for kw in keywords[:8]
        ]
        seniority = "senior" if "senior" in job.title.lower() else ("intern" if "intern" in job.title.lower() else "mid")
        return JDAnalysisOutput(seniority=seniority, keywords=keywords, requirements=reqs), None

    def retrieve_facts(
        self,
        db: Session,
        user: User,
        jd_analysis: JDAnalysisOutput,
    ) -> tuple[list[ProfileFact], list[str], dict[str, ProfileFact]]:
        """Stage 2: Retrieve matching profile_facts and identify unsupported JD requirements (gaps)."""
        facts = list_profile_facts(db, user.id)
        if not facts and user.profile is not None:
            facts = rebuild_profile_facts(db, user, vector_store=self.vector_store)

        fact_map = {str(f.id): f for f in facts}
        all_corpus = " ".join(f"{f.text} {f.source_section}" for f in facts).lower()

        vs = self.vector_store or get_facts_vector_store()
        if facts:
            vs.upsert_chunks(
                str(user.id),
                [
                    {
                        "id": str(f.id),
                        "text": f"[{f.source_section}] {f.text}",
                        "metadata": {"fact_id": str(f.id), "category": f.category},
                    }
                    for f in facts
                ],
            )

        retrieved_ids: list[str] = []
        missing_requirements: list[str] = []

        for req in jd_analysis.requirements:
            req_tokens = [k.lower() for k in (req.keywords or [req.requirement]) if len(k) >= 2]
            keyword_hits = [
                f for f in facts
                if any(tok in f"{f.text} {f.source_section}".lower() for tok in req_tokens)
            ]
            # Vector similarity supplement
            vs_hits = vs.query(str(user.id), f"{req.requirement} {' '.join(req.keywords)}", top_k=3)
            for hit in vs_hits:
                fid = str((hit.get("metadata") or {}).get("fact_id", ""))
                if fid in fact_map and float(hit.get("score", 0.0)) >= 0.15:
                    if fact_map[fid] not in keyword_hits:
                        keyword_hits.append(fact_map[fid])

            if not keyword_hits and not any(tok in all_corpus for tok in req_tokens):
                missing_requirements.append(req.requirement)
            else:
                for f in keyword_hits[:4]:
                    if str(f.id) not in retrieved_ids:
                        retrieved_ids.append(str(f.id))

        # Always include experience & project facts so resume stays complete
        for f in facts:
            if f.category in ("experience_bullet", "project_detail") and str(f.id) not in retrieved_ids:
                retrieved_ids.append(str(f.id))

        retrieved_facts = [fact_map[fid] for fid in retrieved_ids if fid in fact_map]
        return retrieved_facts, missing_requirements, fact_map

    def write_bullets(
        self,
        user: User,
        job: Job,
        jd_analysis: JDAnalysisOutput,
        retrieved_facts: list[ProfileFact],
        feedback: str = "",
    ) -> tuple[ResumeWriterOutput, int | None, str]:
        """Stage 3: Generate tailored bullets strictly citing retrieved fact_ids."""
        exp_proj_facts = [f for f in retrieved_facts if f.category in ("experience_bullet", "project_detail")]
        skill_facts = [f for f in retrieved_facts if f.category == "skill"]

        if self.groq.is_configured and retrieved_facts:
            try:
                system_prompt = load_prompt("resume_writer", "v1")
                facts_block = "\n".join(
                    f"- id={f.id} | section={f.source_section} | category={f.category} | text={f.text}"
                    for f in retrieved_facts[:40]
                )
                user_prompt = (
                    f"Target Role: {job.title} at {job.company}\n"
                    f"JD Keywords: {jd_analysis.keywords}\n"
                    f"Candidate Name: {user.name}\n\n"
                    f"Available Verified Profile Facts (cite ONLY these IDs):\n{facts_block}\n"
                )
                if feedback:
                    user_prompt += f"\nFix these verifier issues from the previous draft:\n{feedback}"

                res = self.groq.complete_json(
                    system_prompt, user_prompt, ResumeWriterOutput, temperature=0.1, max_tokens=2500
                )
                return res.data, res.tokens_used, "groq"
            except GroqServiceError as exc:
                logger.warning("Resume writer Groq fallback: %s", exc)

        # Deterministic truthful writer directly from retrieved facts
        jd_kw_lower = [k.lower() for k in jd_analysis.keywords]
        bullets: list[WrittenBulletItem] = []
        for f in exp_proj_facts:
            covered = [
                kw for kw, kw_l in zip(jd_analysis.keywords, jd_kw_lower)
                if kw_l in f.text.lower() or kw_l in f.source_section.lower()
            ]
            section = "Projects" if f.category == "project_detail" else "Experience"
            bullets.append(
                WrittenBulletItem(
                    section=section,
                    text=f.text,
                    fact_ids=[str(f.id)],
                    jd_keywords_covered=covered,
                )
            )

        skills_list = [f.text.replace("Verified summary: ", "").replace("Verified skill: ", "") for f in skill_facts]
        summary = (
            f"Candidate targeting {job.title} at {job.company} with verified experience in "
            f"{', '.join(skills_list[:6]) or 'software engineering'}."
        )
        return (
            ResumeWriterOutput(
                summary=summary,
                bullets=bullets,
                changes_made=[
                    f"Selected and ordered {len(bullets)} verified bullets grounded in {len(retrieved_facts)} profile facts.",
                ],
            ),
            None,
            "deterministic",
        )

    def verify_bullets(
        self,
        bullets: list[WrittenBulletItem],
        fact_map: dict[str, ProfileFact],
    ) -> tuple[list[tuple[WrittenBulletItem, str, str]], int | None]:
        """Stage 4: Audit every bullet against its cited profile_facts."""
        all_corpus = " ".join(f"{f.text} {f.source_section}" for f in fact_map.values())
        verdicts: list[tuple[WrittenBulletItem, str, str]] = []
        llm_verdicts: dict[int, BulletVerificationItem] = {}
        tokens_used: int | None = None

        if self.groq.is_configured and bullets:
            try:
                system_prompt = load_prompt("resume_verifier", "v1")
                lines = []
                for idx, b in enumerate(bullets):
                    cited_texts = [fact_map[fid].text for fid in b.fact_ids if fid in fact_map]
                    lines.append(
                        f"[{idx}] Bullet: {b.text}\n    Cited Facts: {cited_texts or ['NONE']}"
                    )
                res = self.groq.complete_json(
                    system_prompt,
                    "\n".join(lines),
                    ResumeVerifierOutput,
                    temperature=0.0,
                    max_tokens=1500,
                )
                tokens_used = res.tokens_used
                for item in res.data.verifications:
                    llm_verdicts[item.bullet_index] = item
            except GroqServiceError as exc:
                logger.warning("Resume verifier Groq fallback to strict rules: %s", exc)

        for idx, b in enumerate(bullets):
            strict_status, strict_reason = _strict_verify_bullet(b, fact_map, all_corpus)
            if strict_status == "unsupported":
                verdicts.append((b, "unsupported", strict_reason))
            elif idx in llm_verdicts:
                v = llm_verdicts[idx]
                verdicts.append((b, v.status, v.reason or strict_reason))
            else:
                verdicts.append((b, strict_status, strict_reason))

        return verdicts, tokens_used

    def regenerate_single_bullet(
        self,
        db: Session,
        user: User,
        bullet: ResumeBullet,
        job: Job | None = None,
    ) -> ResumeBullet:
        """Regenerate a single bullet strictly from its cited profile facts and re-verify."""
        facts = list_profile_facts(db, user.id)
        fact_map = {str(f.id): f for f in facts}
        cited = [fact_map[fid] for fid in (bullet.fact_ids or []) if fid in fact_map]
        if not cited:
            cited = facts[:3]

        new_text = cited[0].text if cited else bullet.text
        if self.groq.is_configured and cited:
            try:
                system_prompt = load_prompt("resume_writer", "v1")
                facts_block = "\n".join(f"- id={f.id} | text={f.text}" for f in cited)
                role_hint = f" for {job.title} at {job.company}" if job else ""
                res = self.groq.complete_json(
                    system_prompt,
                    f"Rewrite ONE concise resume bullet{role_hint} using ONLY these facts:\n{facts_block}",
                    ResumeWriterOutput,
                    temperature=0.1,
                    max_tokens=512,
                )
                if res.data.bullets:
                    new_text = res.data.bullets[0].text
            except GroqServiceError:
                pass

        candidate = WrittenBulletItem(
            section=bullet.section,
            text=new_text,
            fact_ids=[str(f.id) for f in cited],
            jd_keywords_covered=list(bullet.jd_keywords or []),
        )
        verdicts, _ = self.verify_bullets([candidate], fact_map)
        _, status_val, reason = verdicts[0]
        if status_val == "unsupported" and cited:
            # Safe fallback to exact verified fact text
            new_text = cited[0].text
            status_val = "verified"
            reason = "Reverted to exact verified profile fact."

        bullet.text = new_text
        bullet.fact_ids = [str(f.id) for f in cited]
        bullet.status = status_val
        bullet.reason = reason
        db.add(bullet)
        db.commit()
        db.refresh(bullet)
        return bullet

    def run(self, db: Session, user: User, application: Application, job: Job) -> Document:
        started = time.perf_counter()
        profile = user.profile
        total_tokens = 0
        has_tokens = False

        # Stage 1: JD Analyzer
        jd_analysis, t1 = self.analyze_jd(job)
        if t1 is not None:
            total_tokens += t1
            has_tokens = True

        # Stage 2: Fact Retriever
        retrieved_facts, missing_requirements, fact_map = self.retrieve_facts(db, user, jd_analysis)

        # Stage 3 + 4: Writer & Verifier loop (max 2 loops)
        unsupported_removed: list[dict[str, str]] = []
        loops_used = 0
        feedback = ""
        final_verified: list[tuple[WrittenBulletItem, str, str]] = []
        writer_out: ResumeWriterOutput | None = None
        mode = "deterministic"

        for attempt in range(1, 3):
            loops_used = attempt
            writer_out, tw, mode = self.write_bullets(user, job, jd_analysis, retrieved_facts, feedback=feedback)
            if tw is not None:
                total_tokens += tw
                has_tokens = True

            verdicts, tv = self.verify_bullets(writer_out.bullets, fact_map)
            if tv is not None:
                total_tokens += tv
                has_tokens = True

            bad = [(b, r) for b, st, r in verdicts if st == "unsupported"]
            if not bad:
                final_verified = verdicts
                break

            feedback = "\n".join(f"- Unsupported bullet '{b.text}': {r}" for b, r in bad)
            if attempt == 2:
                # Strip unsupported bullets after max 2 loops
                unsupported_removed = [{"text": b.text, "reason": r} for b, r in bad]
                final_verified = [(b, st, r) for b, st, r in verdicts if st != "unsupported"]

        assert writer_out is not None
        verified_count = sum(1 for _, st, _ in final_verified if st == "verified")
        rephrased_count = sum(1 for _, st, _ in final_verified if st == "rephrased_ok")
        initial_total = len(final_verified) + len(unsupported_removed)
        hallucination_rate = round(len(unsupported_removed) / max(initial_total, 1), 4)

        all_corpus = " ".join(f"{f.text} {f.source_section}" for f in fact_map.values()).lower()
        jd_keywords = jd_analysis.keywords or _extract_jd_keywords(f"{job.title} {job.description}", limit=14)
        matched_keywords = [kw for kw in jd_keywords if kw.lower() in all_corpus]
        missing_keywords = [kw for kw in jd_keywords if kw.lower() not in all_corpus]
        coverage = round((len(matched_keywords) / max(len(jd_keywords), 1)) * 100.0, 1)

        # Build structured resume sections from verified bullets + real profile metadata
        skills = list((profile.skills if profile else []) or [])
        jd_text = f"{job.title}\n{job.description}".lower()
        prioritized_skills = sorted(skills, key=lambda s: (0 if s.lower() in jd_text else 1, s.lower()))

        exp_bullets = [b.text for b, _, _ in final_verified if b.section.lower() != "projects"]
        proj_bullets = [b.text for b, _, _ in final_verified if b.section.lower() == "projects"]

        experience_entries: list[TailoredExperienceEntry] = []
        raw_exps = list((profile.experience if profile else []) or [])
        if raw_exps:
            for idx, exp in enumerate(raw_exps):
                highlights = exp_bullets if idx == 0 and exp_bullets else list(exp.get("highlights", []))
                experience_entries.append(
                    TailoredExperienceEntry(
                        company=exp.get("company", ""),
                        title=exp.get("title", ""),
                        start_date=exp.get("start_date", ""),
                        end_date=exp.get("end_date", ""),
                        location=exp.get("location", ""),
                        highlights=highlights,
                    )
                )
        elif exp_bullets:
            experience_entries.append(
                TailoredExperienceEntry(company="Verified Background", title=job.title, highlights=exp_bullets)
            )

        project_entries: list[TailoredProjectEntry] = []
        for idx, proj in enumerate(list((profile.projects if profile else []) or [])):
            highlights = proj_bullets if idx == 0 and proj_bullets else list(proj.get("highlights", []))
            project_entries.append(
                TailoredProjectEntry(
                    name=proj.get("name", ""),
                    description=proj.get("description", ""),
                    tech_stack=list(proj.get("tech_stack", [])),
                    highlights=highlights,
                )
            )

        tailored = TailoredResumeOutput(
            summary=writer_out.summary,
            skills_highlighted=prioritized_skills,
            experience=experience_entries,
            projects=project_entries,
            education=list((profile.education if profile else []) or []),
            jd_keywords=jd_keywords,
            matched_keywords=matched_keywords,
            missing_keywords=missing_keywords,
            keyword_coverage_score=coverage,
            changes_made=writer_out.changes_made
            + ([f"Removed {len(unsupported_removed)} unsupported bullet(s) during verification."] if unsupported_removed else []),
        )

        verification_report = VerificationReport(
            total_bullets=len(final_verified),
            verified_count=verified_count,
            rephrased_ok_count=rephrased_count,
            unsupported_removed_count=len(unsupported_removed),
            hallucination_rate=hallucination_rate,
            keyword_coverage_score=coverage,
            missing_requirements=missing_requirements,
            unsupported_removed=unsupported_removed,
            loops_used=loops_used,
        )

        rendered_md = render_resume_markdown(user, tailored)
        max_ver = db.scalar(
            select(func.max(Document.version)).where(
                Document.application_id == application.id,
                Document.type == "resume",
            )
        )
        next_version = (max_ver or 0) + 1

        doc = Document(
            user_id=user.id,
            application_id=application.id,
            type="resume",
            content=rendered_md,
            doc_metadata={
                "mode": mode,
                "structured": tailored.model_dump(),
                "keyword_coverage_score": coverage,
                "jd_keywords": jd_keywords,
                "matched_keywords": matched_keywords,
                "missing_keywords": missing_keywords,
                "missing_requirements": missing_requirements,
                "changes_made": tailored.changes_made,
                "verification_report": verification_report.model_dump(),
            },
            version=next_version,
        )
        db.add(doc)
        db.flush()

        for b, st, reason in final_verified:
            db.add(
                ResumeBullet(
                    document_id=doc.id,
                    section=b.section,
                    text=b.text,
                    fact_ids=b.fact_ids,
                    status=st,
                    jd_keywords=b.jd_keywords_covered,
                    reason=reason,
                )
            )
        for rem in unsupported_removed:
            db.add(
                ResumeBullet(
                    document_id=doc.id,
                    section="Removed",
                    text=rem["text"],
                    fact_ids=[],
                    status="unsupported",
                    jd_keywords=[],
                    reason=rem["reason"],
                )
            )

        application.resume_version_id = doc.id
        db.add(application)
        db.commit()
        db.refresh(doc)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"application={application.id}, job='{job.title}' @ '{job.company}'",
            output_summary=(
                f"v{next_version} | verified={verified_count + rephrased_count}/{len(final_verified)} | "
                f"removed={len(unsupported_removed)} | coverage={coverage}%"
            ),
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=total_tokens if has_tokens else None,
            run_id=str(application.id),
        )
        return doc
