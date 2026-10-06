"""Cryptographic and authentication utilities for Astra Multi."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet

if TYPE_CHECKING:
    from astra_multi.persistence.settings_store import SettingsStore


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Hashes a password with PBKDF2-HMAC-SHA256 and 100,000 iterations.

    Returns (hash_hex, salt_hex).
    """
    if salt_hex is None:
        salt_bytes = secrets.token_bytes(16)
        salt_hex = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt_hex)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations=100_000,
    )
    return derived.hex(), salt_hex


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Safely verifies a password against stored PBKDF2 hash using constant-time comparison."""
    calculated_hash, _ = hash_password(password, salt_hex=salt_hex)
    return hmac.compare_digest(calculated_hash, hash_hex)


def ensure_master_encryption_key(settings_store: SettingsStore) -> bytes:
    """Ensures a persistent master encryption key exists in SQLite settings."""
    existing = settings_store.get_setting("master_encryption_key")
    if existing:
        return existing.encode("utf-8")
    new_key = Fernet.generate_key().decode("utf-8")
    settings_store.set_setting("master_encryption_key", new_key)
    return new_key.encode("utf-8")


def ensure_auth_secret_key(settings_store: SettingsStore) -> str:
    """Ensures a persistent JWT signing key exists in SQLite settings."""
    existing = settings_store.get_setting("auth_secret_key")
    if existing:
        return existing
    new_secret = secrets.token_hex(32)
    settings_store.set_setting("auth_secret_key", new_secret)
    return new_secret


def encrypt_secret(plaintext: str, master_key: bytes) -> str:
    """Encrypts sensitive text using Fernet AES-CBC with HMAC authentication."""
    fernet = Fernet(master_key)
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str, master_key: bytes) -> str:
    """Decrypts a Fernet ciphertext back to plaintext string."""
    fernet = Fernet(master_key)
    return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def _b64encode_str(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64decode_str(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding and padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_access_token(
    secret_key: str,
    role: str = "admin",
    expires_in_seconds: int = 86400 * 7,
) -> str:
    """Creates a signed stateless authentication token with expiry."""
    payload = {
        "sub": role,
        "exp": int(time.time()) + expires_in_seconds,
        "jti": secrets.token_hex(8),
    }
    payload_raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode_str(payload_raw)

    sig = hmac.new(
        secret_key.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64encode_str(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_access_token(token: str, secret_key: str) -> dict[str, Any] | None:
    """Verifies HMAC signature and expiration of an access token."""
    parts = token.strip().split(".")
    if len(parts) != 2:
        return None
    payload_b64, sig_b64 = parts

    expected_sig = hmac.new(
        secret_key.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    try:
        provided_sig = _b64decode_str(sig_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, provided_sig):
        return None

    try:
        payload_json = _b64decode_str(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > exp:
        return None

    return payload
