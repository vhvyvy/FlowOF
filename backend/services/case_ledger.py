"""
Append-only ledger for KPI Admin case events.

Public API
----------
    record_event(db, tenant_id, admin_id, event_type, points, *, case_id, notes)
        Insert one immutable entry.  Caller must commit.

    get_admin_ledger(db, tenant_id, admin_id, period_year, period_month)
        Return ledger entries as list[dict].
"""
from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CaseLedger

logger = logging.getLogger("flowof.case_ledger")


async def record_event(
    db: AsyncSession,
    tenant_id: int,
    admin_id: int,
    event_type: str,
    points: float,
    *,
    case_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> CaseLedger:
    """
    Insert an immutable ledger entry and flush (no commit).
    Raises on DB error — callers handle rollback.
    """
    entry = CaseLedger(
        tenant_id=tenant_id,
        admin_id=admin_id,
        case_id=case_id,
        event_type=event_type,
        points=points,
        notes=notes,
    )
    db.add(entry)
    await db.flush()
    logger.info(
        "ledger: tenant=%s admin=%s event=%s points=%+g case=%s",
        tenant_id, admin_id, event_type, points, case_id,
    )
    return entry


async def get_admin_ledger(
    db: AsyncSession,
    tenant_id: int,
    admin_id: int,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
) -> list[dict]:
    """
    Return ledger entries for an admin, newest first.
    Optionally filter to a calendar month.
    """
    q = (
        select(CaseLedger)
        .where(
            CaseLedger.tenant_id == tenant_id,
            CaseLedger.admin_id == admin_id,
        )
        .order_by(CaseLedger.created_at.desc())
    )

    if period_year is not None:
        q = q.where(extract("year", CaseLedger.created_at) == period_year)
    if period_month is not None:
        q = q.where(extract("month", CaseLedger.created_at) == period_month)

    result = await db.execute(q)
    rows = result.scalars().all()

    return [
        {
            "id": r.id,
            "case_id": r.case_id,
            "event_type": r.event_type,
            "points": float(r.points),
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if isinstance(r.created_at, datetime) else str(r.created_at),
        }
        for r in rows
    ]
