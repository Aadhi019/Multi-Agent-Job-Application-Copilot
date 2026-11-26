from pydantic import BaseModel


class GoogleAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class AuthStatusResponse(BaseModel):
    gmail_connected: bool
    gmail_email: str | None = None
    google_oauth_configured: bool
    groq_configured: bool
    groq_model: str
    scopes: list[str]


class GroqTestResponse(BaseModel):
    ok: bool
    model: str
    latency_ms: int | None = None
    message: str
