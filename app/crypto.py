"""
Symmetric encryption for sensitive user data (e.g. OpenAI API keys).
Uses Fernet (AES-128-CBC + HMAC) with SECRET_KEY as the seed.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    from app.config import settings
    # Derive a 32-byte key from SECRET_KEY via SHA-256, then base64-encode for Fernet
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a string. Returns plaintext. Returns empty string on failure."""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ""
