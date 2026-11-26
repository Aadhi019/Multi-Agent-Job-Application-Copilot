from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.evidence import ProfileFact
from app.models.user import Profile, User
from app.services.vector_store import VectorStoreService


def get_facts_vector_store() -> VectorStoreService:
    settings = get_settings()
    return VectorStoreService(persist_dir=settings.chroma_persist_dir, collection_name="profile_facts")


def extract_atomic_facts(user: User, profile: Profile) -> list[dict[str, str]]:
    """Break a user's structured profile and master resume into atomic verifiable facts."""
    facts: list[dict[str, str]] = []
    seen_texts: set[str] = set()

    def _add(category: str, text: str, source_section: str) -> None:
        cleaned = " ".join((text or "").split()).strip()
        if len(cleaned) < 2:
            return
        key = f"{category}::{cleaned.lower()}"
        if key in seen_texts:
            return
        seen_texts.add(key)
        facts.append({"category": category, "text": cleaned, "source_section": source_section})

    # 1. Experience bullets
    for exp in list(profile.experience or []):
        title = str(exp.get("title", "")).strip()
        company = str(exp.get("company", "")).strip()
        dates = " - ".join(p for p in [str(exp.get("start_date", "")).strip(), str(exp.get("end_date", "")).strip()] if p)
        section_label = f"Experience: {title} @ {company}".strip(" @:")
        if dates:
            section_label = f"{section_label} ({dates})"
        for bullet in list(exp.get("highlights", []) or []):
            _add("experience_bullet", str(bullet), section_label)

    # 2. Project details & highlights
    for proj in list(profile.projects or []):
        name = str(proj.get("name", "")).strip() or "Project"
        tech = ", ".join(str(t) for t in (proj.get("tech_stack") or []) if t)
        section_label = f"Project: {name}" + (f" ({tech})" if tech else "")
        desc = str(proj.get("description", "")).strip()
        if desc:
            _add("project_detail", f"{name}: {desc}" + (f" [Tech: {tech}]" if tech else ""), section_label)
        for bullet in list(proj.get("highlights", []) or []):
            _add("project_detail", str(bullet), section_label)

    # 3. Skills with context
    for skill in list(profile.skills or []):
        _add("skill", f"Verified skill: {skill}", "Skills")

    # 4. Education
    for edu in list(profile.education or []):
        inst = str(edu.get("institution", "")).strip()
        deg = str(edu.get("degree", "")).strip()
        yr = str(edu.get("graduation_year", "")).strip()
        gpa = str(edu.get("gpa", "")).strip()
        parts = [p for p in [inst, deg, yr, f"GPA {gpa}" if gpa else ""] if p]
        if parts:
            _add("education", " — ".join(parts), "Education")

    # 5. Certifications or extra lines from master_resume_text
    resume_text = profile.master_resume_text or ""
    cert_block = re.search(
        r"(?:certifications?|awards?)[:\s]*\n(.*?)(?:\n[A-Z][a-z]+:|\Z)",
        resume_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if cert_block:
        for line in cert_block.group(1).splitlines():
            clean_line = line.strip(" -•*\t")
            if clean_line:
                _add("certification", clean_line, "Certifications")

    # If user only uploaded raw master_resume_text without structured experience/projects, extract resume lines
    if not facts and resume_text.strip():
        for raw_line in resume_text.splitlines():
            clean_line = raw_line.strip(" -•*\t")
            if len(clean_line) >= 12 and "@" not in clean_line:
                _add("experience_bullet", clean_line, "Master Resume")

    return facts


def rebuild_profile_facts(
    db: Session,
    user: User,
    vector_store: VectorStoreService | None = None,
) -> list[ProfileFact]:
    """Rebuild profile_facts for a user and index them into VectorStore (ChromaDB / cosine)."""
    assert user.profile is not None
    raw_facts = extract_atomic_facts(user, user.profile)

    db.execute(delete(ProfileFact).where(ProfileFact.user_id == user.id))
    db.flush()

    created: list[ProfileFact] = []
    for item in raw_facts:
        fact_id = uuid.uuid4()
        row = ProfileFact(
            id=fact_id,
            user_id=user.id,
            category=item["category"],
            text=item["text"],
            source_section=item["source_section"][:255],
            embedding_id=f"{user.id}:{fact_id}",
        )
        db.add(row)
        created.append(row)

    db.commit()
    for row in created:
        db.refresh(row)

    vs = vector_store or get_facts_vector_store()
    if created:
        vs.upsert_chunks(
            str(user.id),
            [
                {
                    "id": str(row.id),
                    "text": f"[{row.source_section}] {row.text}",
                    "metadata": {"fact_id": str(row.id), "category": row.category, "source_section": row.source_section},
                }
                for row in created
            ],
        )

    return created


def list_profile_facts(db: Session, user_id: uuid.UUID) -> list[ProfileFact]:
    return list(
        db.scalars(
            select(ProfileFact)
            .where(ProfileFact.user_id == user_id)
            .order_by(ProfileFact.category.asc(), ProfileFact.created_at.asc())
        ).all()
    )
