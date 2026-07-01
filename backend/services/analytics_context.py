"""Build a rich data snapshot of an agency for a given month, for LLM context."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.analytics_context")


def _month_range(year: int, month: int) -> tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _pct_change(current: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return round((current - prev) / abs(prev) * 100, 1)


async def _totals(db: AsyncSession, tenant_id: int, start: date, end: date) -> dict:
    rev = await db.execute(
        text(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE tenant_id=:tid AND date>=:s AND date<=:e"
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )
    revenue = float(rev.scalar() or 0)

    exp = await db.execute(
        text(
            "SELECT COALESCE(SUM(amount), 0) FROM expenses "
            "WHERE tenant_id=:tid AND date>=:s AND date<=:e"
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )
    expenses = float(exp.scalar() or 0)

    profit = revenue - expenses
    margin = round(profit / revenue * 100, 1) if revenue > 0 else 0.0

    return {
        "revenue":    round(revenue,  2),
        "expenses":   round(expenses, 2),
        "profit":     round(profit,   2),
        "margin_pct": margin,
    }


async def build_agency_snapshot(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
) -> dict[str, Any]:
    start, end = _month_range(year, month)
    py, pm = _prev_month(year, month)
    pstart, pend = _month_range(py, pm)

    totals      = await _totals(db, tenant_id, start, end)
    totals_prev = await _totals(db, tenant_id, pstart, pend)

    deltas = {
        "revenue_pct": _pct_change(totals["revenue"],  totals_prev["revenue"]),
        "profit_pct":  _pct_change(totals["profit"],   totals_prev["profit"]),
    }

    # ── By model: revenue + plan ──────────────────────────────────────────────
    by_model_r = await db.execute(
        text(
            """SELECT COALESCE(mo.name, t.model, '(без модели)') AS model,
                      COALESCE(SUM(t.amount), 0)                 AS revenue
               FROM transactions t
               LEFT JOIN models mo ON mo.id = t.model_id AND mo.tenant_id = :tid
               WHERE t.tenant_id = :tid AND t.date >= :s AND t.date <= :e
               GROUP BY COALESCE(mo.name, t.model, '(без модели)')
               ORDER BY revenue DESC"""
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )
    plan_r = await db.execute(
        text(
            "SELECT model, plan_amount FROM plans "
            "WHERE tenant_id=:tid AND year=:y AND month=:m"
        ),
        {"tid": tenant_id, "y": year, "m": month},
    )
    plan_map: dict[str, float] = {
        r["model"]: float(r["plan_amount"] or 0)
        for r in plan_r.mappings()
    }
    by_model = []
    for r in by_model_r.mappings():
        model   = r["model"]
        revenue = round(float(r["revenue"] or 0), 2)
        plan    = plan_map.get(model)
        pct     = round(revenue / plan * 100, 1) if plan else None
        by_model.append({
            "model":                model,
            "revenue":              revenue,
            "plan":                 round(plan, 2) if plan else None,
            "plan_completion_pct":  pct,
        })

    # ── By shift ──────────────────────────────────────────────────────────────
    by_shift_r = await db.execute(
        text(
            """SELECT COALESCE(sc.name, t.shift_name, '(без смены)') AS shift,
                      COALESCE(SUM(t.amount), 0)                       AS revenue,
                      COUNT(t.id)                                       AS tx_count
               FROM transactions t
               LEFT JOIN shifts_catalog sc ON sc.id = t.shift_catalog_id AND sc.tenant_id = :tid
               WHERE t.tenant_id = :tid AND t.date >= :s AND t.date <= :e
               GROUP BY COALESCE(sc.name, t.shift_name, '(без смены)')
               ORDER BY revenue DESC"""
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )
    by_shift = [
        {
            "shift":    r["shift"],
            "revenue":  round(float(r["revenue"] or 0), 2),
            "tx_count": int(r["tx_count"] or 0),
        }
        for r in by_shift_r.mappings()
    ]

    # ── Top chatters by chatter_id JOIN catalog ───────────────────────────────
    top_chatters_r = await db.execute(
        text(
            """SELECT COALESCE(c.name, t.chatter, '(неизвестен)') AS chatter,
                      COALESCE(SUM(t.amount), 0)                   AS revenue,
                      COUNT(t.id)                                   AS tx_count
               FROM transactions t
               LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = :tid
               WHERE t.tenant_id = :tid AND t.date >= :s AND t.date <= :e
                 AND (t.chatter_id IS NOT NULL OR t.chatter IS NOT NULL)
               GROUP BY COALESCE(c.name, t.chatter, '(неизвестен)')
               ORDER BY revenue DESC
               LIMIT 10"""
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )
    top_chatters = [
        {
            "chatter":  r["chatter"],
            "revenue":  round(float(r["revenue"] or 0), 2),
            "tx_count": int(r["tx_count"] or 0),
        }
        for r in top_chatters_r.mappings()
    ]

    # ── Expenses by category ──────────────────────────────────────────────────
    cat_r = await db.execute(
        text(
            """SELECT COALESCE(ec.name, e.category, '(без категории)') AS category,
                      COALESCE(SUM(e.amount), 0)                         AS amount
               FROM expenses e
               LEFT JOIN expense_categories ec ON ec.id = e.category_id AND ec.tenant_id = :tid
               WHERE e.tenant_id = :tid AND e.date >= :s AND e.date <= :e
               GROUP BY COALESCE(ec.name, e.category, '(без категории)')
               ORDER BY amount DESC"""
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )
    expenses_by_category = [
        {"category": r["category"], "amount": round(float(r["amount"] or 0), 2)}
        for r in cat_r.mappings()
    ]

    return {
        "period":               f"{month:02d}/{year}",
        "period_prev":          f"{pm:02d}/{py}",
        "totals":               totals,
        "totals_prev":          totals_prev,
        "deltas":               deltas,
        "by_model":             by_model,
        "by_shift":             by_shift,
        "top_chatters":         top_chatters,
        "expenses_by_category": expenses_by_category,
    }


def _f(v: float | None, prefix: str = "$") -> str:
    """Format a dollar value nicely, or return 'нет данных'."""
    if v is None:
        return "нет данных"
    return f"{prefix}{v:,.2f}"


def _delta(pct: float | None) -> str:
    if pct is None:
        return ""
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct}% к пред. мес.)"


def snapshot_to_text(snapshot: dict) -> str:
    lines: list[str] = []
    period      = snapshot.get("period", "")
    period_prev = snapshot.get("period_prev", "")
    t           = snapshot.get("totals", {})
    tp          = snapshot.get("totals_prev", {})
    d           = snapshot.get("deltas", {})

    lines.append(f"=== Данные агентства за {period} (пред. {period_prev}) ===\n")

    # Totals
    lines.append("== Финансовое резюме ==")
    lines.append(f"  Выручка:  {_f(t.get('revenue'))}{_delta(d.get('revenue_pct'))}")
    lines.append(f"  Расходы:  {_f(t.get('expenses'))}")
    lines.append(f"  Прибыль:  {_f(t.get('profit'))}{_delta(d.get('profit_pct'))}")
    lines.append(f"  Маржа:    {t.get('margin_pct', 0)}%")
    lines.append(f"  Пред. мес. выручка: {_f(tp.get('revenue'))}, прибыль: {_f(tp.get('profit'))}")

    # By model
    by_model = snapshot.get("by_model") or []
    lines.append("\n== Выручка по моделям ==")
    if by_model:
        for m in by_model:
            plan_str = (
                f", план {_f(m['plan'])} → {m['plan_completion_pct']}%"
                if m.get("plan") else ", план не задан"
            )
            lines.append(f"  {m['model']}: {_f(m['revenue'])}{plan_str}")
    else:
        lines.append("  нет данных")

    # By shift
    by_shift = snapshot.get("by_shift") or []
    lines.append("\n== Выручка по сменам ==")
    if by_shift:
        for s in by_shift:
            lines.append(f"  {s['shift']}: {_f(s['revenue'])} ({s['tx_count']} транзакций)")
    else:
        lines.append("  нет данных")

    # Top chatters
    top = snapshot.get("top_chatters") or []
    lines.append("\n== Топ чаттеров (до 10) ==")
    if top:
        for i, c in enumerate(top, 1):
            lines.append(f"  {i}. {c['chatter']}: {_f(c['revenue'])} ({c['tx_count']} транзакций)")
    else:
        lines.append("  нет данных")

    # Expenses by category
    cats = snapshot.get("expenses_by_category") or []
    lines.append("\n== Расходы по категориям ==")
    if cats:
        for e in cats:
            lines.append(f"  {e['category']}: {_f(e['amount'])}")
    else:
        lines.append("  нет данных")

    return "\n".join(lines)
