"""KPI calculation service — shared logic for the KPI router and reports."""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import date

from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from economics import DEFAULT_TIER, RETENTION_RATE, _tier_pct
from models import ChatterKpi, ChatterMapping, Plan, Transaction
from schemas import KpiRow

logger = logging.getLogger("flowof.kpi_service")

# Onlymonster internal IDs that should not appear in reports
HIDDEN_IDS: set[str] = {"9680", "18073", "71191", "73588", "79737", "80144", "@hornykabanchik"}


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _month_range(year: int, month: int) -> tuple[date, date]:
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _safe(v: float | None, digits: int = 2) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _pct_delta(current: float | None, prev: float | None) -> float | None:
    """% change from prev to current. None if prev is 0 or missing."""
    if prev is None or current is None or prev == 0:
        return None
    return round((current - prev) / abs(prev) * 100, 1)


def _pp_delta(current: float | None, prev: float | None) -> float | None:
    """Percentage-point delta (for rates like PPV Open Rate)."""
    if prev is None or current is None:
        return None
    return round(current - prev, 1)


def _resolve_kpi(
    chatter: str,
    kpi_data: dict[str, dict],
    name_to_id: dict[str, str],
) -> tuple[dict, str | None]:
    """Resolve Onlymonster metrics for a chatter display name."""
    s = str(chatter).strip()
    if s in kpi_data:
        return kpi_data[s], name_to_id.get(s)
    oid = name_to_id.get(s)
    if oid and oid in kpi_data:
        return kpi_data[oid], oid
    if oid:
        for alias in [oid, f"@{oid}"]:
            if alias in kpi_data:
                return kpi_data[alias], oid
    for k, m in kpi_data.items():
        ks = str(k).strip()
        if s and ks and (s.startswith(ks) or ks.startswith(s)):
            return m, name_to_id.get(ks)
    return {}, None


def _compute_derived(row: dict, total_revenue: float) -> KpiRow:
    """Compute all derived KPI metrics from base fields."""
    rev  = row["revenue"]
    txns = row["transactions"]
    ppv_or = _safe(row.get("ppv_open_rate"), 1)
    apv    = _safe(row.get("apv"), 2)
    chats  = row.get("total_chats")
    chats_int = int(chats) if chats is not None else None

    rpc       = _safe(rev / chats, 2)           if chats and chats > 0 else None
    ppv_sold  = _safe(rev / apv, 2)             if apv and apv > 0 else None
    apc       = _safe(ppv_sold / chats, 2)      if ppv_sold and chats and chats > 0 else None
    vol_rat   = _safe(chats * (ppv_or / 100), 2) if chats and ppv_or is not None else None
    conv_sc   = _safe((ppv_or or 0) * (apc or 0), 2)               if ppv_or is not None and apc is not None else None
    mono_dep  = _safe((rpc or 0) / (apv or 1) * 100, 2)            if rpc is not None and apv and apv > 0 else None
    prod_idx  = _safe((ppv_sold or 0) / (chats or 1) * (ppv_or or 0), 2) if chats and chats > 0 and ppv_or is not None else None
    eff_rat   = _safe((rpc or 0) / (apv or 1) * (ppv_or or 0), 2)  if rpc is not None and apv and apv > 0 and ppv_or is not None else None

    return KpiRow(
        chatter=row["chatter"],
        onlymonster_id=row.get("onlymonster_id"),
        revenue=round(rev, 2),
        transactions=txns,
        avg_check=round(rev / txns, 2) if txns > 0 else 0.0,
        share_pct=round(rev / total_revenue * 100, 1) if total_revenue > 0 else 0.0,
        payout=round(row.get("payout", 0.0), 2),
        ppv_open_rate=ppv_or,
        apv=apv,
        total_chats=chats_int,
        rpc=rpc,
        ppv_sold=ppv_sold,
        apc_per_chat=apc,
        volume_rating=vol_rat,
        conversion_score=conv_sc,
        monetization_depth=mono_dep,
        productivity_index=prod_idx,
        efficiency_ratio=eff_rat,
        source=row.get("source"),
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

async def load_kpi_data(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
) -> dict[str, dict]:
    """Load Onlymonster metrics keyed by chatter id/name.
    Checks chatter_kpi_mt first, then falls back to legacy chatter_kpi table.
    """
    def _row_to_dict(chatter, ppv, apv, chats, source):
        return {
            "ppv_open_rate": float(ppv)   if ppv   is not None else None,
            "apv":           float(apv)   if apv   is not None else None,
            "total_chats":   int(chats)   if chats is not None else None,
            "source":        source,
        }

    result = await db.execute(
        select(ChatterKpi).where(
            and_(
                ChatterKpi.tenant_id == tenant_id,
                ChatterKpi.year      == year,
                ChatterKpi.month     == month,
            )
        )
    )
    rows = result.scalars().all()
    if rows:
        return {
            str(r.chatter): _row_to_dict(r.chatter, r.ppv_open_rate, r.apv, r.total_chats, r.source)
            for r in rows
        }

    # Fallback: legacy single-tenant table from old Streamlit app
    try:
        legacy = await db.execute(
            text(
                "SELECT chatter, ppv_open_rate, apv, total_chats, source "
                "FROM chatter_kpi WHERE year=:year AND month=:month"
            ),
            {"year": year, "month": month},
        )
        legacy_rows = legacy.all()
        if legacy_rows:
            logger.info("kpi_service: using legacy chatter_kpi table (%d rows)", len(legacy_rows))
            return {
                str(r.chatter): _row_to_dict(
                    r.chatter, r.ppv_open_rate, r.apv, r.total_chats,
                    getattr(r, "source", "legacy"),
                )
                for r in legacy_rows
            }
    except Exception as e:
        logger.debug("legacy chatter_kpi not available: %s", e)

    return {}


async def load_mapping(
    db: AsyncSession,
    tenant_id: int,
) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (id_to_name, name_to_id).
    id_to_name: onlymonster_id -> first display name
    name_to_id: any display name -> onlymonster_id
    """
    result = await db.execute(
        select(ChatterMapping).where(ChatterMapping.tenant_id == tenant_id)
    )
    id_to_name: dict[str, str] = {}
    name_to_id: dict[str, str] = {}
    for m in result.scalars().all():
        oid = str(m.onlymonster_id)
        names_raw = m.display_names or ""
        try:
            names = json.loads(names_raw) if names_raw.startswith("[") else [names_raw]
        except Exception:
            names = [names_raw]
        if names:
            id_to_name[oid] = names[0]
        for n in names:
            n = str(n).strip()
            if n:
                name_to_id[n] = oid
    return id_to_name, name_to_id


async def chatter_txn_stats(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
) -> dict[str, dict]:
    """Returns {chatter_name: {revenue, transactions}} for a given month."""
    start, end = _month_range(year, month)
    result = await db.execute(
        select(
            Transaction.chatter,
            func.sum(Transaction.amount).label("rev"),
            func.count(Transaction.id).label("txn_count"),
        )
        .where(and_(
            Transaction.tenant_id == tenant_id,
            Transaction.date      >= start,
            Transaction.date      <= end,
            Transaction.chatter.isnot(None),
        ))
        .group_by(Transaction.chatter)
    )
    return {
        str(r.chatter): {"revenue": float(r.rev or 0), "transactions": int(r.txn_count or 0)}
        for r in result.all()
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def get_chatter_kpi(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
    use_retention: bool = True,
) -> tuple[list[KpiRow], float, int, float | None]:
    """Build the full KPI rows for a month, including MoM deltas.

    Returns:
        (rows, total_revenue, total_txns, avg_rpc)
    """
    start, end = _month_range(year, month)

    # ── Current month: revenue per chatter ────────────────────────────────────
    chatter_result = await db.execute(
        select(
            Transaction.chatter,
            func.sum(Transaction.amount).label("revenue"),
            func.count(Transaction.id).label("txn_count"),
        )
        .where(and_(
            Transaction.tenant_id == tenant_id,
            Transaction.date      >= start,
            Transaction.date      <= end,
            Transaction.chatter.isnot(None),
        ))
        .group_by(Transaction.chatter)
        .order_by(func.sum(Transaction.amount).desc())
    )
    txn_rows    = chatter_result.all()
    total_rev   = sum(float(r.revenue  or 0) for r in txn_rows)
    total_txns  = sum(int(r.txn_count  or 0) for r in txn_rows)

    # ── Payout per chatter (plan-tier based) ──────────────────────────────────
    chatter_model_result = await db.execute(
        select(Transaction.chatter, Transaction.model, func.sum(Transaction.amount).label("rev"))
        .where(and_(
            Transaction.tenant_id == tenant_id,
            Transaction.date      >= start,
            Transaction.date      <= end,
            Transaction.chatter.isnot(None),
        ))
        .group_by(Transaction.chatter, Transaction.model)
    )
    chatter_model_rows = chatter_model_result.all()

    plan_result = await db.execute(
        select(Plan.model, Plan.plan_amount).where(
            and_(Plan.tenant_id == tenant_id, Plan.year == year, Plan.month == month)
        )
    )
    plan_map = {r.model: float(r.plan_amount or 0) for r in plan_result.all()}

    model_rev_result = await db.execute(
        select(Transaction.model, func.sum(Transaction.amount).label("rev"))
        .where(and_(
            Transaction.tenant_id == tenant_id,
            Transaction.date      >= start,
            Transaction.date      <= end,
        ))
        .group_by(Transaction.model)
    )
    model_total_rev = {r.model: float(r.rev or 0) for r in model_rev_result.all()}

    chatter_payout: dict[str, float] = {}
    for r in chatter_model_rows:
        ch, m, rev = r.chatter, r.model, float(r.rev or 0)
        plan_amt = plan_map.get(m, 0.0)
        tier = max(0.20, _tier_pct(model_total_rev.get(m, rev) / plan_amt)) if plan_amt > 0 else DEFAULT_TIER
        net  = rev * tier * (1 - RETENTION_RATE if use_retention else 1)
        chatter_payout[ch] = chatter_payout.get(ch, 0.0) + net

    # ── Onlymonster mapping & metrics ─────────────────────────────────────────
    _, name_to_id   = await load_mapping(db, tenant_id)
    kpi_data        = await load_kpi_data(db, tenant_id, year, month)

    prev_month = month - 1 if month > 1 else 12
    prev_year  = year      if month > 1 else year - 1
    prev_kpi   = await load_kpi_data(db, tenant_id, prev_year, prev_month)
    prev_stats = await chatter_txn_stats(db, tenant_id, prev_year, prev_month)
    prev_total = sum(v["revenue"] for v in prev_stats.values())

    # ── Build rows ────────────────────────────────────────────────────────────
    rows: list[KpiRow] = []
    for r in txn_rows:
        chatter = str(r.chatter or "Unknown").strip()
        if chatter in HIDDEN_IDS:
            continue
        rev  = float(r.revenue  or 0)
        txns = int(r.txn_count  or 0)

        om_metrics, om_id = _resolve_kpi(chatter, kpi_data, name_to_id)
        prev_om, _        = _resolve_kpi(chatter, prev_kpi,  name_to_id)
        p_stats  = prev_stats.get(chatter, {})
        prev_rev = p_stats.get("revenue", 0.0)
        prev_tx  = p_stats.get("transactions", 0)

        row = _compute_derived({
            "chatter":        chatter,
            "onlymonster_id": om_id,
            "revenue":        rev,
            "transactions":   txns,
            "payout":         chatter_payout.get(chatter, 0.0),
            **om_metrics,
        }, total_rev)

        prev_row = _compute_derived({
            "chatter":        chatter,
            "onlymonster_id": om_id,
            "revenue":        prev_rev,
            "transactions":   prev_tx,
            "payout":         0.0,
            **prev_om,
        }, prev_total) if prev_rev > 0 or prev_om else None

        row.revenue_delta       = _pct_delta(rev, prev_rev)
        row.transactions_delta  = _pct_delta(txns, prev_tx) if prev_tx > 0 else None
        row.avg_check_delta     = _pct_delta(row.avg_check,    prev_row.avg_check    if prev_row else None)
        row.ppv_open_rate_delta = _pp_delta( row.ppv_open_rate, prev_row.ppv_open_rate if prev_row else None)
        row.apv_delta           = _pct_delta(row.apv,          prev_row.apv           if prev_row else None)
        row.total_chats_delta   = _pct_delta(row.total_chats,  prev_row.total_chats   if prev_row else None)
        row.rpc_delta           = _pct_delta(row.rpc,          prev_row.rpc           if prev_row else None)
        row.ppv_sold_delta      = _pct_delta(row.ppv_sold,     prev_row.ppv_sold      if prev_row else None)
        row.apc_per_chat_delta  = _pct_delta(row.apc_per_chat, prev_row.apc_per_chat  if prev_row else None)
        row.volume_rating_delta = _pct_delta(row.volume_rating, prev_row.volume_rating if prev_row else None)
        row.payout_delta        = _pct_delta(row.payout, prev_rev * DEFAULT_TIER if prev_rev > 0 else None)

        rows.append(row)

    avg_rpc: float | None = None
    total_chats_sum = sum(r.total_chats for r in rows if r.total_chats)
    if total_chats_sum > 0:
        avg_rpc = round(total_rev / total_chats_sum, 2)

    return rows, round(total_rev, 2), total_txns, avg_rpc
