from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import check_db_connection, get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Return service and database health status."""
    settings = get_settings()
    db_ok, db_error = check_db_connection(db)
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        service=settings.app_name,
        environment=settings.environment,
        database="connected" if db_ok else "disconnected",
        database_error=db_error,
        timestamp=datetime.now(timezone.utc),
    )
