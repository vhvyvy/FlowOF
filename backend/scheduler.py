"""Периодический Notion-синк в процессе (APScheduler). Включение: ENABLE_SCHEDULER=1."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("flowof.scheduler")

_scheduler: Any = None


def setup_scheduler() -> Any:
    global _scheduler
    if os.getenv("ENABLE_SCHEDULER", "").strip().lower() not in ("1", "true", "yes"):
        logger.info("scheduler disabled (set ENABLE_SCHEDULER=1 to enable)")
        return None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning("apscheduler not installed; scheduler skipped")
        return None

    from sqlalchemy import select

    from database import AsyncSessionLocal
    from models import Tenant
    from notion_sync_service import sync_notion_transactions_for_tenant
    from services.notion_unify import resolve_notion_token_for_sync

    sched = AsyncIOScheduler()

    async def _job() -> None:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Tenant).where(Tenant.active.is_(True)))
            tenants = list(r.scalars().all())
            for t in tenants:
                tok = await resolve_notion_token_for_sync(db, t)
                if not tok:
                    continue
                try:
                    await sync_notion_transactions_for_tenant(
                        db, t.id, tok, shift_type="relation"
                    )
                except Exception as e:
                    logger.warning("scheduled notion sync tenant=%s: %s", t.id, e)

    sched.add_job(_job, "interval", hours=24, id="notion_sync_all", replace_existing=True)
    sched.start()
    _scheduler = sched
    logger.info("APScheduler started: Notion sync every 24h")
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.debug("scheduler shutdown: %s", e)
        _scheduler = None
