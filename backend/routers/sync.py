"""Ручная синхронизация Notion → БД (Neon)."""
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant
from notion_expense_sync_service import sync_notion_expenses_for_tenant
from notion_sync_service import sync_notion_transactions_for_tenant
from schemas import NotionSyncResult
from services.notion_unify import resolve_notion_token_for_sync

logger = logging.getLogger("flowof.sync")
router = APIRouter(prefix="/api/v1", tags=["sync"])


@router.post("/sync/notion-transactions", response_model=NotionSyncResult)
async def post_sync_notion_transactions(
    shift_type: str = Query("relation", description="relation или select — тип поля смены в Notion"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Забирает все страницы из баз Notion и пишет в `transactions`.

    Нужно:
    - `tenants.notion_token` (интеграция Notion с доступом к базам),
    - ID баз: переменная окружения `NOTION_TRANSACTIONS_DATABASE_ID` и/или `notion_database_id` у команд.

    После импорта проставляет `team_id` по совпадению `notion_database_id`.
    """
    token = await resolve_notion_token_for_sync(db, tenant)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="У тенанта нет notion_token. Добавьте токен в профиле или в tenant_sources.",
        )
    try:
        st = shift_type.strip().lower()
        if st not in ("relation", "select"):
            st = "relation"
        stats = await sync_notion_transactions_for_tenant(
            db,
            tenant.id,
            token,
            shift_type=st,
        )
        exp = await sync_notion_expenses_for_tenant(db, tenant.id, token)
        msg = (
            f"Готово: +{stats['inserted']} новых, обновлено {stats['updated']}, "
            f"пропущено {stats['skipped']} (без модели: {stats.get('skipped_no_model', 0)}, ошибка разбора: {stats.get('skipped_parse', 0)}), "
            f"баз {stats['databases']}, team_id проставлен строк: {stats['assigned_rows']}. "
            f"Расходы: +{exp['inserted']} новых, обновлено {exp['updated']}, пропущено {exp['skipped']}."
        )
        return NotionSyncResult(
            inserted=stats["inserted"],
            updated=stats["updated"],
            skipped=stats["skipped"],
            skipped_no_model=stats.get("skipped_no_model", 0),
            skipped_parse=stats.get("skipped_parse", 0),
            databases=stats["databases"],
            assigned_rows=stats["assigned_rows"],
            message=msg,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("notion sync failed tenant=%s", tenant.id)
        raise HTTPException(status_code=500, detail=str(e)) from e


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
