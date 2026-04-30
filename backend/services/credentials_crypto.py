"""Шифрование JSON credentials для tenant_sources (Fernet)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("flowof.crypto")

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore[misc, assignment]
    InvalidToken = Exception  # type: ignore[misc, assignment]


def _get_fernet() -> Fernet | None:
    key = (os.getenv("CREDENTIALS_FERNET_KEY") or "").strip()
    if not key or Fernet is None:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        logger.warning("CREDENTIALS_FERNET_KEY invalid: %s", e)
        return None


def encrypt_credentials_blob(data: dict[str, Any]) -> dict[str, Any]:
    """
    Если задан CREDENTIALS_FERNET_KEY — возвращает {"_enc": "<fernet token>"}.
    Иначе возвращает data как есть (только для dev).
    """
    f = _get_fernet()
    if f is None:
        if os.getenv("CREDENTIALS_FERNET_KEY"):
            logger.warning("cryptography missing; storing credentials unencrypted")
        return data
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    token = f.encrypt(raw).decode("ascii")
    return {"_enc": token}


def decrypt_credentials_blob(stored: Any) -> dict[str, Any]:
    if not isinstance(stored, dict):
        return {}
    if "_enc" not in stored:
        return dict(stored)
    f = _get_fernet()
    if f is None:
        logger.warning("cannot decrypt credentials: no valid Fernet key")
        return {}
    try:
        raw = f.decrypt(stored["_enc"].encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except InvalidToken:
        logger.warning("credentials decrypt failed")
        return {}
    except Exception as e:
        logger.warning("credentials decrypt error: %s", e)
        return {}
