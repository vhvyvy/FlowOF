"""
Case activities — service layer for admin portal activity log + screenshots.

Public API
----------
    create_activity(db, tenant_id, case_id, admin_id, activity_type, text,
                    uploaded_files) -> dict
    list_activities(db, tenant_id, case_id, filters) -> dict
    delete_activity(db, tenant_id, case_id, admin_id, activity_id) -> None

Errors (mapped to HTTP in routers)
----------------------------------
    CaseActivityNotFound  → 404
    PermissionError       → 403
    CaseActivityValidation → 422
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import AdminCase, CaseActivity, CaseActivityFile
from services.file_storage import CASE_ACTIVITIES_DIR, get_storage_root

logger = logging.getLogger("flowof.case_activities")

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_LEN = 5000
DELETE_WINDOW_HOURS = 24
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

ACTIVITY_TYPES: frozenset[str] = frozenset({
    "review", "training", "meeting", "observation", "note", "other",
})

_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}
_ALLOWED_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})


class CaseActivityNotFound(LookupError):
    """Case or activity not found for tenant."""


class CaseActivityValidation(ValueError):
    """Invalid input (text, type, files)."""


@dataclass
class ActivityFilters:
    activity_types: Optional[list[str]] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    has_files: Optional[bool] = None
    text_search: Optional[str] = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_case(
    db: AsyncSession, tenant_id: int, case_id: int
) -> AdminCase:
    row = (
        await db.execute(
            select(AdminCase).where(
                AdminCase.id == case_id,
                AdminCase.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise CaseActivityNotFound("Кейс не найден")
    return row


def _validate_activity_type(activity_type: str) -> str:
    t = (activity_type or "").strip().lower()
    if t not in ACTIVITY_TYPES:
        raise CaseActivityValidation(
            f"Недопустимый activity_type: {activity_type!r}. "
            f"Допустимо: {', '.join(sorted(ACTIVITY_TYPES))}"
        )
    return t


def _validate_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise CaseActivityValidation("Текст активности не может быть пустым")
    if len(cleaned) > MAX_TEXT_LEN:
        raise CaseActivityValidation(
            f"Текст активности не длиннее {MAX_TEXT_LEN} символов"
        )
    return cleaned


def _ext_from_mime(mime_type: str) -> str:
    mime = (mime_type or "").strip().lower()
    if not mime.startswith("image/"):
        return ""
    ext = _MIME_TO_EXT.get(mime, "")
    if ext and ext in _ALLOWED_EXTS:
        return ext
    return ""


async def _read_and_validate_file(upload: UploadFile, index: int) -> tuple[bytes, str, str, str]:
    """Return (content, mime, ext, original_name)."""
    original = (upload.filename or f"file_{index}").strip() or f"file_{index}"
    mime = (upload.content_type or "").strip().lower()

    if not mime.startswith("image/"):
        raise CaseActivityValidation(
            f"Файл «{original}»: допустимы только изображения (image/*)"
        )

    ext = _ext_from_mime(mime)
    if not ext:
        raise CaseActivityValidation(
            f"Файл «{original}»: неподдерживаемый тип {mime!r} "
            f"(допустимо: PNG, JPEG, WebP)"
        )

    content = await upload.read()
    size = len(content)
    if size > MAX_FILE_BYTES:
        raise CaseActivityValidation(
            f"Файл «{original}»: размер {size} байт превышает лимит 5 МБ"
        )
    if size == 0:
        raise CaseActivityValidation(f"Файл «{original}»: пустой файл")

    return content, mime, ext, original


def _build_paths(case_id: int, ext: str, now: datetime) -> tuple[str, Path]:
    """Relative path (for DB) and absolute path (for disk)."""
    fname = f"{uuid4()}{ext}"
    rel = (
        f"{CASE_ACTIVITIES_DIR}/{now.year:04d}/{now.month:02d}/"
        f"case_{case_id}/{fname}"
    )
    abs_path = get_storage_root() / rel
    return rel, abs_path


def _delete_files_best_effort(paths: list[Path]) -> None:
    for p in paths:
        try:
            if p.is_file():
                p.unlink()
                logger.info("file_storage: deleted %s", p)
        except OSError as exc:
            logger.warning("file_storage: failed to delete %s: %s", p, exc)


@asynccontextmanager
async def _write_transaction(db: AsyncSession):
    """
    One write transaction. Uses savepoint when session already has an open
    transaction (e.g. after prior SELECT in the same request).
    """
    if db.in_transaction():
        async with db.begin_nested():
            yield
    else:
        async with db.begin():
            yield


def _serialize_file(f: CaseActivityFile) -> dict[str, Any]:
    return {
        "id": f.id,
        "file_path": f.file_path,
        "original_name": f.original_name,
        "size_bytes": f.size_bytes,
        "mime_type": f.mime_type,
    }


def _serialize_activity(act: CaseActivity) -> dict[str, Any]:
    admin = act.admin
    admin_name = (admin.full_name or admin.email or "").strip() if admin else ""
    return {
        "id": act.id,
        "activity_type": act.activity_type,
        "text": act.text,
        "created_at": act.created_at,
        "updated_at": act.updated_at,
        "admin": {"id": act.admin_id, "name": admin_name},
        "files": [_serialize_file(f) for f in (act.files or [])],
    }


def _apply_list_filters(q, filters: ActivityFilters):
    if filters.activity_types:
        types = [t.strip().lower() for t in filters.activity_types if t.strip()]
        invalid = [t for t in types if t not in ACTIVITY_TYPES]
        if invalid:
            raise CaseActivityValidation(f"Недопустимые типы фильтра: {', '.join(invalid)}")
        if types:
            q = q.where(CaseActivity.activity_type.in_(types))

    if filters.date_from is not None:
        q = q.where(func.date(CaseActivity.created_at) >= filters.date_from)
    if filters.date_to is not None:
        q = q.where(func.date(CaseActivity.created_at) <= filters.date_to)

    if filters.has_files is True:
        q = q.where(
            exists().where(CaseActivityFile.activity_id == CaseActivity.id)
        )
    elif filters.has_files is False:
        q = q.where(
            ~exists().where(CaseActivityFile.activity_id == CaseActivity.id)
        )

    if filters.text_search:
        term = filters.text_search.strip()
        if term:
            q = q.where(CaseActivity.text.ilike(f"%{term}%"))

    return q


# ── Public API ────────────────────────────────────────────────────────────────

async def create_activity(
    db: AsyncSession,
    tenant_id: int,
    case_id: int,
    admin_id: int,
    activity_type: str,
    text: str,
    uploaded_files: Optional[list[UploadFile]] = None,
) -> dict[str, Any]:
    """
    Create activity with optional image attachments.
    Single transaction; rolls back DB and removes written files on failure.
    """
    atype = _validate_activity_type(activity_type)
    body = _validate_text(text)
    files_in = uploaded_files or []

    if len(files_in) > MAX_FILES:
        raise CaseActivityValidation(f"Не более {MAX_FILES} файлов на активность")

    case = await _load_case(db, tenant_id, case_id)
    if case.admin_id != admin_id:
        raise PermissionError("Только автор кейса может добавлять активности")

    prepared: list[tuple[bytes, str, str, str]] = []
    for i, uf in enumerate(files_in):
        prepared.append(await _read_and_validate_file(uf, i))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    written_abs: list[Path] = []
    activity_id: int | None = None
    created_at: datetime | None = None

    try:
        async with _write_transaction(db):
            activity = CaseActivity(
                tenant_id=tenant_id,
                case_id=case_id,
                admin_id=admin_id,
                activity_type=atype,
                text=body,
                created_at=now,
                updated_at=now,
            )
            db.add(activity)
            await db.flush()

            for content, mime, ext, original in prepared:
                rel_path, abs_path = _build_paths(case_id, ext, now)
                try:
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_bytes(content)
                except OSError as exc:
                    raise CaseActivityValidation(
                        f"Не удалось сохранить файл «{original}» на диск: {exc}"
                    ) from exc

                written_abs.append(abs_path)
                db.add(
                    CaseActivityFile(
                        activity_id=activity.id,
                        file_path=rel_path,
                        original_name=original,
                        mime_type=mime,
                        size_bytes=len(content),
                        created_at=now,
                    )
                )

            activity_id = activity.id
            created_at = activity.created_at

        return {
            "activity_id": activity_id,
            "created_at": created_at,
            "files_count": len(prepared),
        }
    except Exception:
        _delete_files_best_effort(written_abs)
        raise


async def list_activities(
    db: AsyncSession,
    tenant_id: int,
    case_id: int,
    filters: Optional[ActivityFilters] = None,
) -> dict[str, Any]:
    """List activities for a case with files and admin name."""
    await _load_case(db, tenant_id, case_id)

    f = filters or ActivityFilters()
    limit = min(max(f.limit, 1), MAX_LIMIT)
    offset = max(f.offset, 0)

    base = select(CaseActivity).where(
        CaseActivity.tenant_id == tenant_id,
        CaseActivity.case_id == case_id,
    )
    base = _apply_list_filters(base, f)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base.options(
            selectinload(CaseActivity.files),
            selectinload(CaseActivity.admin),
        )
        .order_by(CaseActivity.created_at.desc(), CaseActivity.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_q)).scalars().unique().all()

    return {
        "items": [_serialize_activity(a) for a in rows],
        "total": total,
    }


async def delete_activity(
    db: AsyncSession,
    tenant_id: int,
    case_id: int,
    admin_id: int,
    activity_id: int,
) -> None:
    """Delete activity within 24h window; remove files from disk after commit."""
    await _load_case(db, tenant_id, case_id)

    act = (
        await db.execute(
            select(CaseActivity)
            .options(selectinload(CaseActivity.files))
            .where(
                CaseActivity.id == activity_id,
                CaseActivity.tenant_id == tenant_id,
                CaseActivity.case_id == case_id,
            )
        )
    ).scalar_one_or_none()

    if act is None:
        raise CaseActivityNotFound("Активность не найдена")

    if act.admin_id != admin_id:
        raise PermissionError("Только автор активности может удалить запись")

    age = datetime.utcnow() - act.created_at
    if age > timedelta(hours=DELETE_WINDOW_HOURS):
        raise PermissionError("Срок для удаления истёк")

    disk_paths = [
        get_storage_root() / f.file_path
        for f in (act.files or [])
        if f.file_path
    ]

    async with _write_transaction(db):
        await db.delete(act)

    _delete_files_best_effort(disk_paths)
