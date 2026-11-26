from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.schemas.profile import (
    EducationItem,
    ExperienceItem,
    ParsedProfileFields,
    ProjectItem,
)
from app.services.groq import GroqService, GroqServiceError

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

RESUME_PARSE_SYSTEM_PROMPT = """You are a strict, truthful resume parser.
Extract structured profile fields ONLY from information explicitly present in the resume text.
NEVER invent skills, employers, job titles, dates, metrics, or education.
If a field is missing in the resume text, leave it empty."""


class ResumeParseError(Exception):
    """Raised when an uploaded resume cannot be parsed."""


def extract_text_from_upload(filename: str, content: bytes) -> str:
    """Extract plain text from an uploaded PDF, DOCX, TXT, or MD resume."""
    if not content:
        raise ResumeParseError("Uploaded file is empty.")

    ext = Path(filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ResumeParseError(
            f"Unsupported file type '{ext or 'unknown'}'. Upload a PDF, DOCX, TXT, or MD file."
        )

    if ext in {".txt", ".md"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
        cleaned = text.strip()
        if not cleaned:
            raise ResumeParseError("Uploaded text resume contains no readable text.")
        return cleaned

    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            cleaned = "\n\n".join(p.strip() for p in pages if p.strip()).strip()
        except Exception as exc:
            raise ResumeParseError(f"Failed to read PDF file: {exc}") from exc
        if not cleaned:
            raise ResumeParseError(
                "Could not extract text from PDF. If it is a scanned image PDF, upload a text-based PDF or DOCX."
            )
        return cleaned

    # .docx
    try:
        doc = DocxDocument(io.BytesIO(content))
        parts: list[str] = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        cleaned = "\n".join(parts).strip()
    except Exception as exc:
        raise ResumeParseError(f"Failed to read DOCX file: {exc}") from exc

    if not cleaned:
        raise ResumeParseError("Uploaded DOCX resume contains no readable text.")
    return cleaned


def heuristic_parse_resume(resume_text: str) -> ParsedProfileFields:
    """Deterministic fallback parser when Groq API is unavailable or unconfigured."""
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", resume_text)
    email = email_match.group(0) if email_match else None

    name: str | None = None
    if lines:
        first_line = lines[0]
        if "@" not in first_line and len(first_line.split()) <= 5 and len(first_line) <= 60:
            name = first_line

    skills: list[str] = []
    skills_section = re.search(
        r"(?:^|\n)(?:technical\s+)?skills[:\s]*\n?(.*?)(?:\n(?:experience|work|projects|education)\b|\Z)",
        resume_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if skills_section:
        raw_skills = skills_section.group(1)
        for token in re.split(r"[,|•;\n]+", raw_skills):
            cleaned_token = re.sub(r"^[A-Za-z\s]+:\s*", "", token).strip(" -*\t")
            if 1 < len(cleaned_token) <= 40 and cleaned_token not in skills:
                skills.append(cleaned_token)

    experience: list[ExperienceItem] = []
    projects: list[ProjectItem] = []
    education: list[EducationItem] = []

    edu_match = re.search(
        r"(?:^|\n)education[:\s]*\n(.*?)(?:\n(?:experience|skills|projects|certifications)\b|\Z)",
        resume_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if edu_match:
        edu_lines = [l.strip(" -•*") for l in edu_match.group(1).splitlines() if l.strip()]
        if edu_lines:
            education.append(EducationItem(institution=edu_lines[0], degree=" ".join(edu_lines[1:2])))

    return ParsedProfileFields(
        name=name,
        email=email,
        skills=skills[:30],
        experience=experience,
        projects=projects,
        education=education,
    )


def parse_resume_to_profile_fields(
    resume_text: str,
    groq_service: GroqService | None = None,
) -> tuple[ParsedProfileFields, str]:
    """Extract structured profile fields using Groq JSON mode, falling back to heuristics."""
    service = groq_service or GroqService()
    if service.is_configured:
        try:
            result = service.complete_json(
                RESUME_PARSE_SYSTEM_PROMPT,
                f"Parse this master resume into structured profile fields:\n\n{resume_text[:12000]}",
                ParsedProfileFields,
                temperature=0.0,
            )
            return result.data, "groq"
        except GroqServiceError as exc:
            logger.warning("Groq resume parsing failed, falling back to heuristics: %s", exc)

    return heuristic_parse_resume(resume_text), "heuristic"
