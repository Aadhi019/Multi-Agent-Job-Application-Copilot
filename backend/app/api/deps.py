from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.user import Profile, User

DEFAULT_USER_EMAIL = "copilot@local.dev"
DEFAULT_USER_NAME = "Job Seeker"


def get_current_user(db: Session = Depends(get_db)) -> User:
    """Return the active local user, creating a default user + empty profile on first run."""
    user = db.scalar(select(User).order_by(User.created_at.asc()))
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL, name=DEFAULT_USER_NAME)
        db.add(user)
        db.flush()
        profile = Profile(
            user_id=user.id,
            skills=[],
            experience=[],
            projects=[],
            education=[],
            preferences={},
            master_resume_text="",
        )
        db.add(profile)
        db.commit()
        db.refresh(user)
    elif user.profile is None:
        profile = Profile(
            user_id=user.id,
            skills=[],
            experience=[],
            projects=[],
            education=[],
            preferences={},
            master_resume_text="",
        )
        db.add(profile)
        db.commit()
        db.refresh(user)
    return user
