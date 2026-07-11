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

    # ── Daily KPI collection (optional, ENABLE_KPI_DAILY=1) ──────────────────
    kpi_daily_enabled = os.getenv("ENABLE_KPI_DAILY", "").strip().lower() in ("1", "true", "yes")

    if kpi_daily_enabled:
        async def _kpi_daily_job() -> None:
            """04:00 UTC: collect yesterday's Onlymonster KPI for all tenants with OM key."""
            from datetime import date, timedelta
            from services.kpi_daily import collect_daily_kpi

            yesterday = date.today() - timedelta(days=1)

            async with AsyncSessionLocal() as db:
                r = await db.execute(
                    select(Tenant)
                    .where(
                        Tenant.active.is_(True),
                        Tenant.onlymonster_key.isnot(None),
                        Tenant.onlymonster_key != "",
                    )
                )
                tenants = list(r.scalars().all())

            logger.info("kpi_daily job: %d tenants with OM key, date=%s", len(tenants), yesterday)
            for t in tenants:
                try:
                    async with AsyncSessionLocal() as db:
                        result = await collect_daily_kpi(db, t.id, yesterday)
                        if result.get("error"):
                            logger.warning(
                                "kpi_daily job tenant=%s: %s", t.id, result["error"]
                            )
                        else:
                            logger.info(
                                "kpi_daily job tenant=%s date=%s written=%s",
                                t.id, yesterday, result.get("records_written"),
                            )
                except Exception as exc:
                    logger.warning("kpi_daily job error tenant=%s: %s", t.id, exc)

        sched.add_job(
            _kpi_daily_job,
            "cron",
            hour=4, minute=0,
            id="kpi_daily_collect",
            replace_existing=True,
        )

    # ── Admin KPI HOLD review (optional, ENABLE_ADMIN_KPI=1) ─────────────────
    admin_kpi_enabled = os.getenv("ENABLE_ADMIN_KPI", "").strip().lower() in ("1", "true", "yes")

    if admin_kpi_enabled:
        async def _check_review_due_cases_job() -> None:
            """05:00 UTC: process all HOLD cases whose review_date <= today."""
            from services.case_review_service import check_review_due_cases

            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Tenant).where(Tenant.active.is_(True)))
                tenants = list(r.scalars().all())

            logger.info("hold_review job: processing %d tenants", len(tenants))
            for t in tenants:
                try:
                    async with AsyncSessionLocal() as db:
                        stats = await check_review_due_cases(db, t.id)
                    logger.info(
                        "hold_review processed: tenant=%s processed=%s "
                        "closed_success=%s guardrail=%s needs_review=%s errors=%s",
                        t.id,
                        stats.get("processed", 0),
                        stats.get("closed_success", 0),
                        stats.get("guardrail", 0),
                        stats.get("needs_review", 0),
                        stats.get("errors", []),
                    )
                except Exception as exc:
                    logger.warning("hold_review job error tenant=%s: %s", t.id, exc)

            logger.info("hold_review job DONE")

        sched.add_job(
            _check_review_due_cases_job,
            "cron",
            hour=5, minute=0,
            id="admin_kpi_hold_review",
            replace_existing=True,
        )

    # ── Nightly KPI snapshot recalc (optional, ENABLE_ADMIN_KPI_NIGHTLY=1) ───
    admin_kpi_nightly_enabled = os.getenv(
        "ENABLE_ADMIN_KPI_NIGHTLY", ""
    ).strip().lower() in ("1", "true", "yes")

    if admin_kpi_nightly_enabled:
        async def _nightly_kpi_snapshot_recalc_job() -> None:
            """04:30 UTC: recalc current-month admin_kpi_snapshot for all admins."""
            from services.admin_kpi_calc import nightly_recalc_all_tenant_snapshots

            try:
                stats = await nightly_recalc_all_tenant_snapshots()
                logger.info(
                    "nightly_kpi_snapshot_recalc DONE: tenants=%s admins=%s errors=%s",
                    stats.get("tenants", 0),
                    stats.get("admins", 0),
                    len(stats.get("errors", [])),
                )
            except Exception as exc:
                logger.error("nightly_kpi_snapshot_recalc job error: %s", exc, exc_info=True)

        sched.add_job(
            _nightly_kpi_snapshot_recalc_job,
            "cron",
            hour=4, minute=30,
            id="nightly_kpi_snapshot_recalc",
            replace_existing=True,
        )

    # ── Agent Watcher jobs (optional, AGENT_WATCHER_ENABLED=1) ────────────────
    watcher_enabled = os.getenv("AGENT_WATCHER_ENABLED", "").strip().lower() in ("1", "true", "yes")

    if watcher_enabled:
        async def _watcher_scan_job() -> None:
            """Daily proactive scan: find anomalies and create accepted events."""
            from services.agent_watcher import watcher_scan

            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Tenant).where(Tenant.active.is_(True)))
                tenants = list(r.scalars().all())

            total_created = 0
            for t in tenants:
                try:
                    async with AsyncSessionLocal() as db:
                        result = await watcher_scan(db, t.id)
                        total_created += result.get("total", 0)
                        logger.info(
                            "watcher_scan tenant=%s level_a=%s level_b=%s",
                            t.id, result.get("level_a"), result.get("level_b"),
                        )
                except Exception as exc:
                    logger.warning("watcher_scan scheduler error tenant=%s: %s", t.id, exc)

            logger.info("watcher_scan job DONE: total events created=%s", total_created)

        async def _watcher_review_job() -> None:
            """Daily review: check past-deadline events and update outcomes."""
            from services.agent_watcher import watcher_review

            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Tenant).where(Tenant.active.is_(True)))
                tenants = list(r.scalars().all())

            total_updated = 0
            for t in tenants:
                try:
                    async with AsyncSessionLocal() as db:
                        result = await watcher_review(db, t.id)
                        total_updated += result.get("updated", 0)
                        logger.info(
                            "watcher_review tenant=%s checked=%s updated=%s",
                            t.id, result.get("checked"), result.get("updated"),
                        )
                except Exception as exc:
                    logger.warning("watcher_review scheduler error tenant=%s: %s", t.id, exc)

            logger.info("watcher_review job DONE: total events updated=%s", total_updated)

        sched.add_job(
            _watcher_scan_job,
            "cron",
            hour=6, minute=0,
            id="agent_watcher_scan",
            replace_existing=True,
        )
        sched.add_job(
            _watcher_review_job,
            "cron",
            hour=7, minute=0,
            id="agent_watcher_review",
            replace_existing=True,
        )

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
    kpi_daily_msg   = " + KPI daily 04:00 UTC" if kpi_daily_enabled else ""
    admin_kpi_msg   = " + HOLD review 05:00 UTC" if admin_kpi_enabled else ""
    admin_kpi_nightly_msg = (
        " + KPI snapshot recalc 04:30 UTC" if admin_kpi_nightly_enabled else ""
    )
    watcher_msg     = " + Watcher scan 06:00 + Watcher review 07:00 UTC" if watcher_enabled else ""
    job_count = (
        3
        + (1 if kpi_daily_enabled else 0)
        + (1 if admin_kpi_enabled else 0)
        + (1 if admin_kpi_nightly_enabled else 0)
        + (2 if watcher_enabled else 0)
    )
    logger.info(
        "APScheduler started with %d jobs: Notion sync every 24h, MMR daily 03:00 UTC, "
        "Season close 23:55 UTC%s%s%s%s",
        job_count, kpi_daily_msg, admin_kpi_nightly_msg, admin_kpi_msg, watcher_msg,
    )
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.debug("scheduler shutdown: %s", e)
        _scheduler = None
