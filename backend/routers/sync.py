"""Ручная синхронизация Notion → БД (Neon).

Импорт делается в фоновой задаче, чтобы Railway/Cloudflare не обрезали HTTP-запрос
по таймауту. Фронт опрашивает /sync/status и видит прогресс/итог/ошибку.
"""
import logging
import os
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from dependencies import get_current_tenant
from models import SyncLog, Tenant, Transaction
from notion_expense_sync_service import sync_notion_expenses_for_tenant
from notion_sync_service import NOTION_VERSION, sync_notion_transactions_for_tenant
from services.notion_unify import resolve_notion_token_for_sync

logger = logging.getLogger("flowof.sync")
router = APIRouter(prefix="/api/v1", tags=["sync"])


# ───────────────────────────── Background runner ─────────────────────────────

# Tenants currently running a sync (in-process lock to prevent double-clicks)
_RUNNING_TENANTS: set[int] = set()


async def _run_notion_sync_bg(tenant_id: int, token: str, shift_type: str) -> None:
    """
    Долгоживущая задача: импорт транзакций + расходов с записью статуса в sync_log.
    Открывает свою сессию БД, чтобы не зависеть от scope HTTP-запроса.
    """
    if tenant_id in _RUNNING_TENANTS:
        logger.warning("notion sync already running for tenant=%s — skip", tenant_id)
        return
    _RUNNING_TENANTS.add(tenant_id)
    try:
        async with AsyncSessionLocal() as db:
            # sync_log записывается внутри sync_notion_transactions_for_tenant.
            # Здесь оборачиваем верхним try/except чтобы при падении пометить running → error.
            log_id: int | None = None
            try:
                stats = await sync_notion_transactions_for_tenant(
                    db, tenant_id, token, shift_type=shift_type
                )
                exp = await sync_notion_expenses_for_tenant(db, tenant_id, token)
                msg = (
                    f"Готово: +{stats['inserted']} новых, обновлено {stats['updated']}, "
                    f"пропущено {stats['skipped']} (без модели: {stats.get('skipped_no_model', 0)}, "
                    f"ошибка разбора: {stats.get('skipped_parse', 0)}), баз {stats['databases']}, "
                    f"team_id проставлен строк: {stats['assigned_rows']}. "
                    f"Расходы: +{exp['inserted']} новых, обновлено {exp['updated']}, "
                    f"пропущено {exp['skipped']}."
                )
                # Найдём только что созданный sync_log (последний для этого тенанта) и сохраним сводку
                last = await db.execute(
                    select(SyncLog)
                    .where(SyncLog.tenant_id == tenant_id)
                    .order_by(desc(SyncLog.id))
                    .limit(1)
                )
                row = last.scalar_one_or_none()
                if row:
                    row.status = "success"
                    row.error_message = msg  # храним сводку в том же поле — фронт читает оттуда
                    row.finished_at = datetime.utcnow()
                    await db.commit()
            except Exception as e:
                logger.exception("notion sync (bg) failed tenant=%s", tenant_id)
                # Помечаем последний running лог как error
                try:
                    last = await db.execute(
                        select(SyncLog)
                        .where(SyncLog.tenant_id == tenant_id)
                        .order_by(desc(SyncLog.id))
                        .limit(1)
                    )
                    row = last.scalar_one_or_none()
                    if row and row.status == "running":
                        row.status = "error"
                        row.error_message = str(e)[:2000]
                        row.finished_at = datetime.utcnow()
                        await db.commit()
                    else:
                        # sync_log ещё не создавался (упало до flush) → создаём
                        new_log = SyncLog(
                            tenant_id=tenant_id,
                            source_type="notion",
                            started_at=datetime.utcnow(),
                            finished_at=datetime.utcnow(),
                            status="error",
                            error_message=str(e)[:2000],
                            rows_imported=0,
                            rows_skipped=0,
                        )
                        db.add(new_log)
                        await db.commit()
                except Exception:
                    logger.exception("failed to write error sync_log tenant=%s", tenant_id)
    finally:
        _RUNNING_TENANTS.discard(tenant_id)


# ───────────────────────────── HTTP endpoints ─────────────────────────────


class SyncStatusOut(BaseModel):
    """Состояние последней синхронизации."""
    status: str  # 'idle' | 'running' | 'success' | 'error' | 'never'
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rows_imported: int = 0
    rows_skipped: int = 0
    message: str | None = None


class SyncStartOut(BaseModel):
    started: bool
    message: str


@router.post("/sync/notion-transactions", response_model=SyncStartOut)
async def post_sync_notion_transactions(
    background_tasks: BackgroundTasks,
    shift_type: str = Query("relation", description="relation или select — тип поля смены в Notion"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Запускает импорт в фоне и сразу возвращает ответ. Прогресс/итог — через GET /sync/status.
    """
    token = await resolve_notion_token_for_sync(db, tenant)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="У тенанта нет notion_token. Добавьте токен в профиле или в tenant_sources.",
        )
    if tenant.id in _RUNNING_TENANTS:
        return SyncStartOut(started=False, message="Синхронизация уже идёт. Проверяйте статус.")
    st = shift_type.strip().lower()
    if st not in ("relation", "select"):
        st = "relation"
    background_tasks.add_task(_run_notion_sync_bg, tenant.id, token, st)
    logger.info("notion sync queued tenant=%s shift_type=%s", tenant.id, st)
    return SyncStartOut(
        started=True,
        message="Импорт запущен в фоне. Можно закрыть страницу — он не прервётся.",
    )


@router.get("/sync/status", response_model=SyncStatusOut)
async def get_sync_status(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Возвращает состояние последнего sync_log для текущего тенанта.
    Поле `message` содержит:
      - сводку «Готово: …» при success;
      - текст исключения при error;
      - None при running.
    """
    r = await db.execute(
        select(SyncLog)
        .where(SyncLog.tenant_id == tenant.id, SyncLog.source_type == "notion")
        .order_by(desc(SyncLog.id))
        .limit(1)
    )
    last = r.scalar_one_or_none()
    if not last:
        return SyncStatusOut(status="never")
    # Если в памяти процесса флаг running выставлен — явно сообщаем running, даже если
    # лог ещё не успел переключиться (на случай гонки).
    if tenant.id in _RUNNING_TENANTS and last.status not in ("success", "error"):
        return SyncStatusOut(
            status="running",
            started_at=last.started_at,
            rows_imported=last.rows_imported or 0,
            rows_skipped=last.rows_skipped or 0,
        )
    return SyncStatusOut(
        status=last.status or "idle",
        started_at=last.started_at,
        finished_at=last.finished_at,
        rows_imported=last.rows_imported or 0,
        rows_skipped=last.rows_skipped or 0,
        message=last.error_message,
    )


@router.get("/sync/debug-chatter-fields")
async def debug_chatter_fields(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Берёт до 3 транзакций с chatter=NULL и запрашивает их свойства напрямую из Notion.
    Возвращает dict: notion_id → {prop_name: {type, value_summary}}.
    Помогает понять почему поле чаттера не парсится.
    """
    token = await resolve_notion_token_for_sync(db, tenant)
    if not token:
        raise HTTPException(status_code=400, detail="Нет Notion token")

    rows = (await db.execute(
        select(Transaction.notion_id)
        .where(
            Transaction.tenant_id == tenant.id,
            Transaction.chatter.is_(None),
            Transaction.notion_id.isnot(None),
        )
        .limit(3)
    )).all()

    if not rows:
        return {"message": "Нет транзакций с chatter=NULL — всё ок!"}

    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Notion-Version": NOTION_VERSION,
    }

    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for (nid,) in rows:
            raw = (nid or "").replace("-", "")
            if len(raw) != 32:
                continue
            page_id = f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
            r = await client.get(f"https://api.notion.com/v1/pages/{page_id}", headers=headers)
            if r.status_code != 200:
                result[page_id] = {"error": r.text[:200]}
                continue
            props = r.json().get("properties") or {}
            summary: dict[str, Any] = {}
            for k, v in props.items():
                t = v.get("type") if isinstance(v, dict) else None
                val: Any = None
                if t == "rich_text":
                    arr = v.get("rich_text") or []
                    val = "".join(x.get("plain_text", "") for x in arr)[:80]
                elif t == "select":
                    val = (v.get("select") or {}).get("name")
                elif t == "multi_select":
                    val = [x.get("name") for x in v.get("multi_select") or []]
                elif t == "people":
                    val = [x.get("name") for x in v.get("people") or []]
                elif t == "formula":
                    f = v.get("formula") or {}
                    val = f"{f.get('type')}: {f.get(f.get('type'), '')}"
                elif t == "relation":
                    val = f"{len(v.get('relation') or [])} relations"
                elif t == "rollup":
                    ro = v.get("rollup") or {}
                    val = f"rollup({ro.get('type')})"
                elif t == "title":
                    val = "".join(x.get("plain_text", "") for x in v.get("title") or [])[:80]
                elif t == "number":
                    val = v.get("number")
                elif t == "date":
                    val = (v.get("date") or {}).get("start")
                else:
                    val = t
                summary[k] = {"type": t, "value": val}
            result[page_id] = summary

    return result


class RunAllSyncResult(BaseModel):
    tenants_with_token: int
    tenants_synced: int
    errors: list[str]


@router.post("/sync/run-all", response_model=RunAllSyncResult)
async def post_sync_run_all(
    x_sync_secret: str | None = Header(None, alias="X-Sync-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """
    Массовый Notion-синк для всех активных тенантов с токеном.
    Защита: заголовок `X-Sync-Secret` = переменная окружения `SYNC_CRON_SECRET`.
    """
    secret = (os.getenv("SYNC_CRON_SECRET") or "").strip()
    if not secret or (x_sync_secret or "").strip() != secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    r = await db.execute(select(Tenant).where(Tenant.active.is_(True)))
    tenants = list(r.scalars().all())
    errors: list[str] = []
    synced = 0
    with_token = 0
    for t in tenants:
        tok = await resolve_notion_token_for_sync(db, t)
        if not tok:
            continue
        with_token += 1
        try:
            await sync_notion_transactions_for_tenant(
                db, t.id, tok, shift_type="relation"
            )
            await sync_notion_expenses_for_tenant(db, t.id, tok)
            synced += 1
        except Exception as e:
            errors.append(f"tenant {t.id}: {e!s}"[:500])
            logger.warning("run-all sync tenant %s: %s", t.id, e)
    return RunAllSyncResult(
        tenants_with_token=with_token,
        tenants_synced=synced,
        errors=errors[:100],
    )
