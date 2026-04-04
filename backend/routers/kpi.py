import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, ChatterMapping
from schemas import KpiResponse, KpiRow

logger = logging.getLogger("skynet.kpi")
router = APIRouter(prefix="/api/v1", tags=["kpi"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.get("/kpi", response_model=KpiResponse)
async def get_kpi(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        # Chatter → onlymonster mapping
        mapping_result = await db.execute(
            select(ChatterMapping).where(ChatterMapping.tenant_id == tenant.id)
        )
        mapping = {m.onlymonster_id: m.display_names for m in mapping_result.scalars().all()}

        # Revenue by chatter for the period
        chatter_result = await db.execute(
            select(
                Transaction.chatter,
                func.sum(Transaction.amount).label("revenue"),
                func.count(Transaction.id).label("txn_count"),
            )
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                    Transaction.chatter.isnot(None),
                )
            )
            .group_by(Transaction.chatter)
            .order_by(func.sum(Transaction.amount).desc())
        )
        rows = chatter_result.all()

        total_revenue = sum(float(r.revenue or 0) for r in rows)
        total_txns = sum(int(r.txn_count or 0) for r in rows)

        kpi_rows: list[KpiRow] = []
        for r in rows:
            rev = float(r.revenue or 0)
            txns = int(r.txn_count or 0)
            rpc = round(rev / txns, 2) if txns > 0 else 0.0

            # Try to find onlymonster_id by matching chatter name in display_names
            om_id = None
            for oid, names_json in mapping.items():
                if r.chatter and r.chatter in (names_json or ""):
                    om_id = oid
                    break

            kpi_rows.append(
                KpiRow(
                    chatter=r.chatter or "Unknown",
                    onlymonster_id=om_id,
                    messages_sent=txns,
                    revenue=round(rev, 2),
                    rpc=rpc,
                )
            )

        avg_rpc = round(total_revenue / total_txns, 2) if total_txns > 0 else 0.0

        return KpiResponse(
            rows=kpi_rows,
            total_messages=total_txns,
            total_revenue=round(total_revenue, 2),
            avg_rpc=avg_rpc,
        )

    except Exception as e:
        logger.error("kpi error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки KPI")


@router.get("/kpi/mapping", tags=["kpi"])
async def get_mapping(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatterMapping).where(ChatterMapping.tenant_id == tenant.id)
    )
    return [
        {"id": m.id, "onlymonster_id": m.onlymonster_id, "display_names": m.display_names}
        for m in result.scalars().all()
    ]
