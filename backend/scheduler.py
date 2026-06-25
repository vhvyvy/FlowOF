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

    async def _notion_job() -> None:
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

    async def _mmr_daily_job() -> None:
        """Daily MMR recalc for all active tenants — today + yesterday."""
        from datetime import date, timedelta
        from services.mmr_trigger import trigger_mmr_recalc

        today     = date.today()
        yesterday = today - timedelta(days=1)

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Tenant).where(Tenant.active.is_(True)))
            tenants = list(r.scalars().all())

        for t in tenants:
            for target_date in (yesterday, today):
                try:
                    await trigger_mmr_recalc(t.id, target_date, reason="scheduler")
                except Exception as exc:
                    logger.warning("MMR scheduler error tenant=%s date=%s: %s", t.id, target_date, exc)

    async def _season_close_job() -> None:
        """
        23:55 UTC: check active seasons whose end_date == today and close them.
        The next process_day call will auto-create the new season via _get_or_create_active_season.
        """
        from datetime import date
        from sqlalchemy import text
        from services.season_service import SeasonService

        today = date.today()
        logger.info("Season auto-close check: date=%s", today)

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    text(
                        "SELECT id, name FROM mmr_seasons "
                        "WHERE is_active = TRUE AND end_date = :today"
                    ),
                    {"today": today},
                )
                seasons_to_close = list(result.mappings())

            for s in seasons_to_close:
                logger.info("Auto-closing season id=%s name=%s", s["id"], s["name"])
                try:
                    async with AsyncSessionLocal() as db:
                        svc = SeasonService()
                        result = await svc.close_season(s["id"], db)
                        logger.info(
                            "Auto-close done: season id=%s name=%s chatters=%s top3=%s",
                            s["id"], s["name"],
                            result.get("chatters_finalized", 0),
                            result.get("top_3", []),
                        )
                except Exception as exc:
                    logger.error("Auto-close failed season id=%s: %s", s["id"], exc, exc_info=True)
        except Exception as exc:
            logger.error("Season auto-close job error: %s", exc, exc_info=True)

    sched.add_job(_notion_job, "interval", hours=24, id="notion_sync_all", replace_existing=True)
    sched.add_job(
        _mmr_daily_job,
        "cron",
        hour=3, minute=0,
        id="mmr_daily",
        replace_existing=True,
    )
    sched.add_job(
        _season_close_job,
        "cron",
        hour=23, minute=55,
        id="season_auto_close",
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("APScheduler started: Notion sync every 24h, MMR daily 03:00 UTC, Season close 23:55 UTC")
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.debug("scheduler shutdown: %s", e)
        _scheduler = None
