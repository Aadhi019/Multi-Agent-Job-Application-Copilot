from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import sign_oauth_state, verify_oauth_state
from app.models.user import User
from app.schemas.auth import AuthStatusResponse, GoogleAuthStartResponse, GroqTestResponse
from app.services.gmail import GMAIL_SCOPES, GmailConfigError, GmailService, GmailServiceError
from app.services.groq import GroqService, GroqServiceError

router = APIRouter(prefix="/auth", tags=["auth"])


class _GroqPing(BaseModel):
    status: str
    reply: str


@router.get("/status", response_model=AuthStatusResponse)
def get_auth_status(user: User = Depends(get_current_user)) -> AuthStatusResponse:
    """Return Gmail OAuth connection status and Groq configuration readiness."""
    gmail = GmailService()
    groq = GroqService()
    return AuthStatusResponse(
        gmail_connected=bool(user.gmail_credentials_encrypted),
        gmail_email=user.gmail_email,
        google_oauth_configured=gmail.is_configured,
        groq_configured=groq.is_configured,
        groq_model=groq.model,
        scopes=GMAIL_SCOPES,
    )


@router.post("/google", response_model=GoogleAuthStartResponse)
def start_google_oauth(user: User = Depends(get_current_user)) -> GoogleAuthStartResponse:
    """Generate a Google OAuth2 authorization URL with read+draft Gmail scopes."""
    gmail = GmailService()
    state = sign_oauth_state(str(user.id))
    try:
        auth_url = gmail.build_auth_url(state)
    except GmailConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GoogleAuthStartResponse(auth_url=auth_url, state=state)


@router.get("/callback")
def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    format: str = Query(default="redirect"),
    db: Session = Depends(get_db),
):
    """Handle Google OAuth2 callback, encrypt tokens, and persist on user."""
    settings = get_settings()
    frontend_settings_url = f"{settings.frontend_url.rstrip('/')}/settings"

    if error:
        if format == "json":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth error: {error}")
        return RedirectResponse(f"{frontend_settings_url}?gmail=error&reason={quote(error)}")

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'code' or 'state' query parameter in OAuth callback.",
        )

    try:
        user_id_str = verify_oauth_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    import uuid

    user = db.get(User, uuid.UUID(user_id_str))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    gmail = GmailService()
    try:
        token_payload = gmail.exchange_code_for_tokens(code)
    except GmailServiceError as exc:
        if format == "json":
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        return RedirectResponse(f"{frontend_settings_url}?gmail=error&reason={quote(str(exc))}")

    gmail.store_user_credentials(user, token_payload, db)

    if format == "json":
        return JSONResponse(
            {
                "gmail_connected": True,
                "gmail_email": user.gmail_email,
                "scopes": token_payload.get("scopes", GMAIL_SCOPES),
            }
        )
    return RedirectResponse(f"{frontend_settings_url}?gmail=connected")


@router.post("/google/disconnect", response_model=AuthStatusResponse)
def disconnect_google_oauth(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthStatusResponse:
    """Disconnect stored Gmail OAuth credentials."""
    gmail = GmailService()
    gmail.disconnect_user(user, db)
    groq = GroqService()
    return AuthStatusResponse(
        gmail_connected=False,
        gmail_email=None,
        google_oauth_configured=gmail.is_configured,
        groq_configured=groq.is_configured,
        groq_model=groq.model,
        scopes=GMAIL_SCOPES,
    )


@router.post("/groq/test", response_model=GroqTestResponse)
def test_groq_connection() -> GroqTestResponse:
    """Verify Groq API connectivity and JSON-mode schema validation."""
    groq = GroqService()
    if not groq.is_configured:
        return GroqTestResponse(
            ok=False,
            model=groq.model,
            message="GROQ_API_KEY is not configured in .env.",
        )
    try:
        res = groq.complete_json(
            "Respond with status='ok' and a short greeting in reply.",
            "Ping check",
            _GroqPing,
            max_tokens=128,
        )
        return GroqTestResponse(
            ok=True,
            model=res.model,
            latency_ms=res.latency_ms,
            message=res.data.reply,
        )
    except GroqServiceError as exc:
        return GroqTestResponse(ok=False, model=groq.model, message=str(exc))
