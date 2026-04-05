"""Ручная синхронизация Notion → БД (Neon)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db
from dependencies import get_current_tenant
from models import Tenant
from notion_sync_service import sync_notion_transactions_for_tenant
from schemas import NotionSyncResult
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("skynet.sync")
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
    if not tenant.notion_token or not str(tenant.notion_token).strip():
        raise HTTPException(
            status_code=400,
            detail="У тенанта нет notion_token. Добавьте токен в таблицу tenants (Neon) или через админ-API.",
        )
    try:
        st = shift_type.strip().lower()
        if st not in ("relation", "select"):
            st = "relation"
        stats = await sync_notion_transactions_for_tenant(
            db,
            tenant.id,
            str(tenant.notion_token).strip(),
            shift_type=st,
        )
        msg = (
            f"Готово: +{stats['inserted']} новых, обновлено {stats['updated']}, "
            f"пропущено {stats['skipped']} (без модели: {stats.get('skipped_no_model', 0)}, ошибка разбора: {stats.get('skipped_parse', 0)}), "
            f"баз {stats['databases']}, team_id проставлен строк: {stats['assigned_rows']}"
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
