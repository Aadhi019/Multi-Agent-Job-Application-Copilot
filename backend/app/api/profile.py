import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.evidence import ProfileFact
from app.models.user import Profile, User
from app.schemas.evidence import (
    ProfileFactCreateRequest,
    ProfileFactResponse,
    ProfileFactUpdateRequest,
)
from app.schemas.profile import (
    EducationItem,
    ExperienceItem,
    ParsedProfileFields,
    PreferencesSchema,
    ProfileResponse,
    ProfileUpdateRequest,
    ProjectItem,
    ResumeUploadResponse,
)
from app.agents.job_discovery import JobDiscoveryAgent
from app.services.facts_extractor import list_profile_facts, rebuild_profile_facts
from app.services.resume_parser import (
    ResumeParseError,
    extract_text_from_upload,
    parse_resume_to_profile_fields,
)

router = APIRouter(prefix="/profile", tags=["profile"])


def _serialize_profile(user: User, profile: Profile) -> ProfileResponse:
    return ProfileResponse(
        user_id=user.id,
        name=user.name,
        email=user.email,
        skills=list(profile.skills or []),
        experience=[ExperienceItem.model_validate(item) for item in (profile.experience or [])],
        projects=[ProjectItem.model_validate(item) for item in (profile.projects or [])],
        education=[EducationItem.model_validate(item) for item in (profile.education or [])],
        preferences=PreferencesSchema.model_validate(profile.preferences or {}),
        master_resume_text=profile.master_resume_text or "",
    )


@router.get("", response_model=ProfileResponse)
def get_profile(user: User = Depends(get_current_user)) -> ProfileResponse:
    """Retrieve the current user's profile and master resume."""
    assert user.profile is not None
    return _serialize_profile(user, user.profile)


@router.put("", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileResponse:
    """Update structured profile fields, preferences, or master resume text."""
    assert user.profile is not None
    profile = user.profile

    if payload.name is not None:
        user.name = payload.name.strip() or user.name
    if payload.email is not None and payload.email.strip():
        user.email = payload.email.strip()
    if payload.skills is not None:
        profile.skills = [s.strip() for s in payload.skills if s.strip()]
    if payload.experience is not None:
        profile.experience = [item.model_dump() for item in payload.experience]
    if payload.projects is not None:
        profile.projects = [item.model_dump() for item in payload.projects]
    if payload.education is not None:
        profile.education = [item.model_dump() for item in payload.education]
    if payload.preferences is not None:
        profile.preferences = payload.preferences.model_dump()
    if payload.master_resume_text is not None:
        profile.master_resume_text = payload.master_resume_text

    db.add(user)
    db.add(profile)
    db.commit()
    db.refresh(user)
    db.refresh(profile)
    rebuild_profile_facts(db, user)
    JobDiscoveryAgent().rescore_user_jobs(db, user, use_llm=False)
    return _serialize_profile(user, profile)


@router.post("/resume", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    auto_populate: bool = Form(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeUploadResponse:
    """Upload a PDF, DOCX, TXT, or MD resume, extract text, and optionally populate fields."""
    assert user.profile is not None
    profile = user.profile

    content = await file.read()
    filename = file.filename or "resume.txt"

    try:
        extracted_text = extract_text_from_upload(filename, content)
    except ResumeParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    profile.master_resume_text = extracted_text

    if auto_populate:
        parsed_fields, parser_mode = parse_resume_to_profile_fields(extracted_text)
        if parsed_fields.name:
            user.name = parsed_fields.name
        if parsed_fields.email:
            user.email = parsed_fields.email
        if parsed_fields.skills:
            profile.skills = parsed_fields.skills
        if parsed_fields.experience:
            profile.experience = [item.model_dump() for item in parsed_fields.experience]
        if parsed_fields.projects:
            profile.projects = [item.model_dump() for item in parsed_fields.projects]
        if parsed_fields.education:
            profile.education = [item.model_dump() for item in parsed_fields.education]
    else:
        parsed_fields = ParsedProfileFields()
        parser_mode = "text_only"

    db.add(user)
    db.add(profile)
    db.commit()
    db.refresh(user)
    db.refresh(profile)
    rebuild_profile_facts(db, user)
    JobDiscoveryAgent().rescore_user_jobs(db, user, use_llm=False)

    return ResumeUploadResponse(
        filename=filename,
        extracted_chars=len(extracted_text),
        parser_mode=parser_mode,  # type: ignore[arg-type]
        parsed_fields=parsed_fields,
        profile=_serialize_profile(user, profile),
    )


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


@router.get("/facts", response_model=list[ProfileFactResponse])
def get_facts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProfileFactResponse]:
    """List atomic verifiable facts extracted from the user's profile."""
    facts = list_profile_facts(db, user.id)
    if not facts and user.profile and (
        user.profile.experience or user.profile.projects or user.profile.skills or user.profile.master_resume_text
    ):
        facts = rebuild_profile_facts(db, user)
    return [_serialize_fact(f) for f in facts]


@router.post("/facts/rebuild", response_model=list[ProfileFactResponse])
def rebuild_facts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProfileFactResponse]:
    """Rebuild all atomic profile_facts from the current profile and master resume."""
    facts = rebuild_profile_facts(db, user)
    return [_serialize_fact(f) for f in facts]


@router.post("/facts", response_model=ProfileFactResponse, status_code=status.HTTP_201_CREATED)
def create_fact(
    payload: ProfileFactCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileFactResponse:
    """Add an atomic profile fact manually."""
    fid = uuid.uuid4()
    row = ProfileFact(
        id=fid,
        user_id=user.id,
        category=payload.category,
        text=payload.text.strip(),
        source_section=payload.source_section.strip() or "Manual Entry",
        embedding_id=f"{user.id}:{fid}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_fact(row)


@router.put("/facts/{fact_id}", response_model=ProfileFactResponse)
def update_fact(
    fact_id: uuid.UUID,
    payload: ProfileFactUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileFactResponse:
    """Edit an existing profile fact."""
    row = db.get(ProfileFact, fact_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found.")
    if payload.category is not None:
        row.category = payload.category
    if payload.text is not None:
        row.text = payload.text.strip()
    if payload.source_section is not None:
        row.source_section = payload.source_section.strip()
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_fact(row)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a profile fact."""
    row = db.get(ProfileFact, fact_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found.")
    db.delete(row)
    db.commit()
