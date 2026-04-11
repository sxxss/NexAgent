"""Simple symmetric encryption for API keys stored in the database.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.
Key source:
1. NEXAGENT_SECRET_KEY env var
2. NEXAGENT_DATA_DIR/secret.key, generated once for local development
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_fernet = None


def _data_dir() -> Path:
    data_dir = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _load_or_create_local_secret() -> str:
    from cryptography.fernet import Fernet

    path = _data_dir() / "secret.key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = Fernet.generate_key().decode()
    path.write_text(secret, encoding="utf-8")
    logger.warning(
        "NEXAGENT_SECRET_KEY not set — generated a persistent local secret at %s. "
        "Set NEXAGENT_SECRET_KEY explicitly before production deployment.",
        path,
    )
    return secret


def _normalise_fernet_key(raw: str) -> bytes:
    value = raw.strip()
    try:
        decoded = base64.urlsafe_b64decode(value.encode())
        if len(decoded) == 32:
            return value.encode()
    except Exception:
        pass
    key_bytes = value.encode()[:32].ljust(32, b"\0")
    return base64.urlsafe_b64encode(key_bytes)


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet

        raw = os.environ.get("NEXAGENT_SECRET_KEY", "") or _load_or_create_local_secret()
        key = _normalise_fernet_key(raw)
        _fernet = Fernet(key)
    except ImportError:
        logger.warning("cryptography package not installed — storing API keys as plaintext")
        _fernet = None
    return _fernet


def encrypt_key(plaintext: str) -> str:
    """Encrypt an API key string. Returns ciphertext string."""
    if not plaintext:
        return ""
    f = _get_fernet()
    if f is None:
        return plaintext   # no encryption available
    return f.encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """Decrypt an API key string. Returns plaintext."""
    if not ciphertext:
        return ""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        if ciphertext.startswith("gAAAAA"):
            logger.warning(
                "Could not decrypt stored API key. Re-enter the key once; future restarts will use the stable secret."
            )
            return ""
        # Probably stored before encryption was enabled - return as-is
        return ciphertext
