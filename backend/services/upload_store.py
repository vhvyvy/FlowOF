"""Временное хранение загруженных файлов импорта (in-process; один воркер)."""
from __future__ import annotations

import logging
import tempfile
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger("flowof.upload_store")

TTL_SEC = 3600
_store: dict[str, tuple[Path, float, int]] = {}
_lock = threading.Lock()


def _cleanup() -> None:
    now = time.time()
    dead: list[str] = []
    with _lock:
        for uid, (path, ts, _) in _store.items():
            if now - ts > TTL_SEC:
                dead.append(uid)
        for uid in dead:
            path, _, _ = _store.pop(uid)
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                logger.debug("unlink upload %s: %s", uid, e)


def save_upload(tenant_id: int, content: bytes, suffix: str) -> str:
    _cleanup()
    uid = str(uuid.uuid4())
    path = Path(tempfile.gettempdir()) / f"flowof_imp_{uid}{suffix}"
    path.write_bytes(content)
    with _lock:
        _store[uid] = (path, time.time(), tenant_id)
    return uid


def get_upload_path(upload_id: str, tenant_id: int) -> Path | None:
    _cleanup()
    with _lock:
        row = _store.get(upload_id)
        if not row:
            return None
        path, _, tid = row
        if tid != tenant_id:
            return None
        return path


def pop_upload(upload_id: str, tenant_id: int) -> Path | None:
    """Удалить из кэша и вернуть путь (файл вызывающий удаляет с диска)."""
    with _lock:
        row = _store.pop(upload_id, None)
        if not row:
            return None
        path, _, tid = row
        if tid != tenant_id:
            _store[upload_id] = row
            return None
        return path
