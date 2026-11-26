from fastapi import APIRouter

from app.api.agents import router as agents_router
from app.api.analytics import router as analytics_router
from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.emails import router as emails_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.profile import router as profile_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(profile_router)
api_router.include_router(auth_router)
api_router.include_router(jobs_router)
api_router.include_router(applications_router)
api_router.include_router(documents_router)
api_router.include_router(emails_router)
api_router.include_router(agents_router)
api_router.include_router(analytics_router)
