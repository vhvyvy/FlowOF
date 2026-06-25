"""
MMR auto-recalculation trigger.

Call trigger_mmr_recalc() after any transaction/expense mutation or import.
Uses an in-process debounce dict so bulk imports don't fire dozens of recalcs.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("flowof.mmr_trigger")

# Debounce map: (tenant_id, date_iso) → last_scheduled_ts
_last_scheduled: dict[tuple[int, str], float] = {}
_DEBOUNCE_SECS = 5.0


async def trigger_mmr_recalc(
    tenant_id: int,
    target_date: date,
    reason: str = "mutation",
) -> None:
    """
    Asynchronously trigger MMRService.process_day for tenant+date.

    Safe to call from BackgroundTasks or any async context.
    Debounces repeated calls for the same tenant+date within DEBOUNCE_SECS.
    """
    key = (tenant_id, str(target_date))
    now = time.monotonic()

    last = _last_scheduled.get(key, 0.0)
    if now - last < _DEBOUNCE_SECS:
        logger.debug(
            "MMR auto-recalc debounced: tenant=%s date=%s reason=%s (%.1fs since last)",
            tenant_id, target_date, reason, now - last,
        )
        return

    _last_scheduled[key] = now
    logger.info("MMR auto-recalc: tenant=%s date=%s reason=%s", tenant_id, target_date, reason)

    try:
        from database import AsyncSessionLocal
        from services.mmr_service import MMRService

        async with AsyncSessionLocal() as db:
            service = MMRService(db)
            result = await service.process_day(tenant_id, target_date)
            logger.info(
                "MMR auto-recalc done: tenant=%s date=%s reason=%s events=%s",
                tenant_id, target_date, reason, result.get("events_created", 0),
            )
    except Exception as exc:
        logger.warning(
            "MMR auto-recalc error: tenant=%s date=%s reason=%s error=%s",
            tenant_id, target_date, reason, exc,
        )


async def trigger_mmr_recalc_range(
    tenant_id: int,
    year: int,
    month: int,
    reason: str = "import",
) -> None:
    """
    Recalculate MMR for every day of a given month.
    Used after bulk imports — runs once for the whole month.
    """
    import calendar
    from datetime import timedelta

    logger.info(
        "MMR auto-recalc range: tenant=%s month=%s/%s reason=%s",
        tenant_id, month, year, reason,
    )
    start = date(year, month, 1)
    end   = date(year, month, calendar.monthrange(year, month)[1])

    try:
        from database import AsyncSessionLocal
        from services.mmr_service import MMRService

        async with AsyncSessionLocal() as db:
            service = MMRService(db)
            total_events = 0
            current = start
            while current <= end:
                try:
                    result = await service.process_day(tenant_id, current)
                    total_events += result.get("events_created", 0)
                except Exception as exc:
                    logger.warning("MMR range day error %s: %s", current, exc)
                current += timedelta(days=1)
        logger.info(
            "MMR auto-recalc range done: tenant=%s month=%s/%s events=%s",
            tenant_id, month, year, total_events,
        )
    except Exception as exc:
        logger.warning(
            "MMR auto-recalc range error: tenant=%s month=%s/%s error=%s",
            tenant_id, month, year, exc,
        )
