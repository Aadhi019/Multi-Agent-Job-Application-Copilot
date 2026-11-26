from app.core.config import get_settings
from app.models.user import User
from app.services.gmail import GMAIL_SCOPES, GmailService


def test_auth_status_and_scopes_exclude_send(client):
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["gmail_connected"] is False
    assert "https://www.googleapis.com/auth/gmail.readonly" in data["scopes"]
    assert "https://www.googleapis.com/auth/gmail.compose" in data["scopes"]
    assert "https://www.googleapis.com/auth/gmail.send" not in data["scopes"]
    assert set(data["scopes"]) == set(GMAIL_SCOPES)


def test_google_auth_start_and_callback_encrypts_tokens(client, db_session, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret-456")
    get_settings.cache_clear()

    start_res = client.post("/api/auth/google")
    assert start_res.status_code == 200
    payload = start_res.json()
    assert "accounts.google.com/o/oauth2/v2/auth" in payload["auth_url"]
    assert "gmail.send" not in payload["auth_url"]
    state = payload["state"]

    monkeypatch.setattr(
        GmailService,
        "exchange_code_for_tokens",
        lambda self, code: {
            "token": "access-abc",
            "refresh_token": "refresh-xyz",
            "scopes": GMAIL_SCOPES,
            "gmail_email": "seeker@gmail.com",
        },
    )

    cb_res = client.get(f"/api/auth/callback?code=authcode123&state={state}&format=json")
    assert cb_res.status_code == 200
    cb_data = cb_res.json()
    assert cb_data["gmail_connected"] is True
    assert cb_data["gmail_email"] == "seeker@gmail.com"

    user = db_session.query(User).first()
    assert user is not None
    assert user.gmail_email == "seeker@gmail.com"
    assert user.gmail_credentials_encrypted is not None
    assert "access-abc" not in user.gmail_credentials_encrypted  # must be encrypted

    disc_res = client.post("/api/auth/google/disconnect")
    assert disc_res.status_code == 200
    assert disc_res.json()["gmail_connected"] is False

    get_settings.cache_clear()
