import base64
import hashlib
import hmac
import time

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    secret = get_settings().secret_key.encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt sensitive tokens before persistence."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt stored sensitive tokens."""
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def sign_oauth_state(user_id: str) -> str:
    """Create an HMAC-signed OAuth state token carrying user_id and issued timestamp."""
    issued_at = str(int(time.time()))
    payload = f"{user_id}:{issued_at}"
    secret = get_settings().secret_key.encode("utf-8")
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def verify_oauth_state(state: str, max_age_seconds: int = 900) -> str:
    """Validate an OAuth state token and return the embedded user_id."""
    try:
        decoded = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
        user_id, issued_at_str, sig = decoded.rsplit(":", 2)
        issued_at = int(issued_at_str)
    except Exception as exc:
        raise ValueError("Invalid OAuth state format") from exc

    payload = f"{user_id}:{issued_at_str}"
    secret = get_settings().secret_key.encode("utf-8")
    expected_sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Invalid OAuth state signature")

    if time.time() - issued_at > max_age_seconds:
        raise ValueError("OAuth state expired")

    return user_id
