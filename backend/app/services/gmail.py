from __future__ import annotations

import base64
import json
import logging
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlencode

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models.user import User

logger = logging.getLogger(__name__)

# Strict least-privilege scopes: read + compose drafts ONLY (never gmail.send)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"


class GmailServiceError(Exception):
    """Base error for Gmail OAuth2 and API operations."""


class GmailConfigError(GmailServiceError):
    """Raised when Google OAuth client credentials are not configured."""


class GmailService:
    """Handles Google OAuth2 (read + draft only) and encrypted token persistence."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        cid = self.settings.google_client_id.strip()
        csec = self.settings.google_client_secret.strip()
        return bool(
            cid
            and csec
            and not cid.startswith("your_")
            and not csec.startswith("your_")
        )

    def build_auth_url(self, state: str) -> str:
        if not self.is_configured:
            raise GmailConfigError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env before connecting Gmail."
            )
        params = {
            "client_id": self.settings.google_client_id,
            "redirect_uri": self.settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange Google OAuth authorization code for tokens and fetch the user's email."""
        if not self.is_configured:
            raise GmailConfigError("Google OAuth client credentials are not configured.")

        payload = {
            "code": code,
            "client_id": self.settings.google_client_id,
            "client_secret": self.settings.google_client_secret,
            "redirect_uri": self.settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
        with httpx.Client(timeout=20.0) as client:
            token_resp = client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
            if token_resp.status_code >= 400:
                raise GmailServiceError(
                    f"Google token exchange failed ({token_resp.status_code}): {token_resp.text}"
                )
            token_data = token_resp.json()

            access_token = token_data.get("access_token")
            if not access_token:
                raise GmailServiceError("Google token response missing access_token.")

            userinfo_resp = client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            gmail_email = None
            if userinfo_resp.status_code == 200:
                gmail_email = userinfo_resp.json().get("email")

        return {
            "token": access_token,
            "refresh_token": token_data.get("refresh_token"),
            "token_uri": GOOGLE_TOKEN_ENDPOINT,
            "client_id": self.settings.google_client_id,
            "client_secret": self.settings.google_client_secret,
            "scopes": token_data.get("scope", " ".join(GMAIL_SCOPES)).split(),
            "gmail_email": gmail_email,
        }

    def store_user_credentials(self, user: User, token_payload: dict[str, Any], db: Session) -> None:
        encrypted = encrypt_secret(json.dumps(token_payload))
        user.gmail_credentials_encrypted = encrypted
        if token_payload.get("gmail_email"):
            user.gmail_email = token_payload["gmail_email"]
        db.add(user)
        db.commit()
        db.refresh(user)

    def disconnect_user(self, user: User, db: Session) -> None:
        user.gmail_credentials_encrypted = None
        user.gmail_email = None
        db.add(user)
        db.commit()
        db.refresh(user)

    def load_user_credentials(self, user: User, db: Session) -> Credentials | None:
        if not user.gmail_credentials_encrypted:
            return None

        raw = json.loads(decrypt_secret(user.gmail_credentials_encrypted))
        creds = Credentials(
            token=raw.get("token"),
            refresh_token=raw.get("refresh_token"),
            token_uri=raw.get("token_uri", GOOGLE_TOKEN_ENDPOINT),
            client_id=raw.get("client_id", self.settings.google_client_id),
            client_secret=raw.get("client_secret", self.settings.google_client_secret),
            scopes=raw.get("scopes", GMAIL_SCOPES),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            raw["token"] = creds.token
            user.gmail_credentials_encrypted = encrypt_secret(json.dumps(raw))
            db.add(user)
            db.commit()
        return creds

    def list_recent_messages(
        self,
        user: User,
        db: Session,
        *,
        max_results: int = 20,
        query: str = "",
    ) -> list[dict[str, str]]:
        creds = self.load_user_credentials(user, db)
        if creds is None:
            raise GmailServiceError("Gmail is not connected for this user.")

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        results = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results, q=query or None)
            .execute()
        )
        messages: list[dict[str, str]] = []
        for item in results.get("messages", []):
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            messages.append(
                {
                    "gmail_message_id": msg["id"],
                    "subject": headers.get("subject", "(No Subject)"),
                    "from": headers.get("from", ""),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )
        return messages

    def create_draft(
        self,
        user: User,
        db: Session,
        *,
        to: str,
        subject: str,
        body: str,
    ) -> dict[str, str]:
        """Create a Gmail draft ONLY. Never sends emails automatically."""
        creds = self.load_user_credentials(user, db)
        if creds is None:
            raise GmailServiceError("Gmail is not connected for this user.")

        mime = EmailMessage()
        mime["To"] = to
        mime["Subject"] = subject
        mime.set_content(body)
        encoded = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
        return {"draft_id": draft.get("id", ""), "message_id": draft.get("message", {}).get("id", "")}
