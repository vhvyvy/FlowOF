"""Build a rich data snapshot of an agency for a given month, for LLM context."""
from __future__ import annotations

import logging
from calendar import monthrange
from collections import defaultdict
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


async def _all_time(db: AsyncSession, tenant_id: int) -> dict:
    # ── Financials ────────────────────────────────────────────────────────────
    tx_r = await db.execute(
        text(
            """SELECT COALESCE(SUM(amount), 0) AS revenue,
                      COUNT(id)                 AS tx_count,
                      MIN(date)                 AS first_date,
                      MAX(date)                 AS last_date,
                      COUNT(DISTINCT DATE_TRUNC('month', date)) AS months_active
               FROM transactions
               WHERE tenant_id = :tid"""
        ),
        {"tid": tenant_id},
    )
    tx_row = tx_r.mappings().one()
    revenue       = float(tx_row["revenue"] or 0)
    tx_count      = int(tx_row["tx_count"] or 0)
    first_tx_date = str(tx_row["first_date"]) if tx_row["first_date"] else None
    last_tx_date  = str(tx_row["last_date"])  if tx_row["last_date"]  else None
    months_active = int(tx_row["months_active"] or 0)

    exp_r = await db.execute(
        text("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE tenant_id=:tid"),
        {"tid": tenant_id},
    )
    expenses = float(exp_r.scalar() or 0)

    profit = revenue - expenses
    margin = round(profit / revenue * 100, 1) if revenue > 0 else 0.0

    # ── Top chatters (all time, by chatter_id JOIN catalog) ───────────────────
    top_r = await db.execute(
        text(
            """SELECT COALESCE(c.name, t.chatter, '(неизвестен)') AS chatter,
                      COALESCE(SUM(t.amount), 0)                   AS revenue,
                      COUNT(t.id)                                   AS tx_count
               FROM transactions t
               LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = :tid
               WHERE t.tenant_id = :tid
                 AND (t.chatter_id IS NOT NULL OR t.chatter IS NOT NULL)
               GROUP BY COALESCE(c.name, t.chatter, '(неизвестен)')
               ORDER BY revenue DESC
               LIMIT 10"""
        ),
        {"tid": tenant_id},
    )
    top_chatters = [
        {
            "chatter":  r["chatter"],
            "revenue":  round(float(r["revenue"] or 0), 2),
            "tx_count": int(r["tx_count"] or 0),
        }
        for r in top_r.mappings()
    ]

    # ── By model (all time) ───────────────────────────────────────────────────
    model_r = await db.execute(
        text(
            """SELECT COALESCE(mo.name, t.model, '(без модели)') AS model,
                      COALESCE(SUM(t.amount), 0)                 AS revenue
               FROM transactions t
               LEFT JOIN models mo ON mo.id = t.model_id AND mo.tenant_id = :tid
               WHERE t.tenant_id = :tid
               GROUP BY COALESCE(mo.name, t.model, '(без модели)')
               ORDER BY revenue DESC"""
        ),
        {"tid": tenant_id},
    )
    by_model = [
        {"model": r["model"], "revenue": round(float(r["revenue"] or 0), 2)}
        for r in model_r.mappings()
    ]

    # ── Expenses by category (all time) ──────────────────────────────────────
    cat_r = await db.execute(
        text(
            """SELECT COALESCE(ec.name, e.category, '(без категории)') AS category,
                      COALESCE(SUM(e.amount), 0)                         AS amount
               FROM expenses e
               LEFT JOIN expense_categories ec ON ec.id = e.category_id AND ec.tenant_id = :tid
               WHERE e.tenant_id = :tid
               GROUP BY COALESCE(ec.name, e.category, '(без категории)')
               ORDER BY amount DESC"""
        ),
        {"tid": tenant_id},
    )
    expenses_by_category = [
        {"category": r["category"], "amount": round(float(r["amount"] or 0), 2)}
        for r in cat_r.mappings()
    ]

    return {
        "revenue":              round(revenue,  2),
        "expenses":             round(expenses, 2),
        "profit":               round(profit,   2),
        "margin_pct":           margin,
        "total_tx_count":       tx_count,
        "first_tx_date":        first_tx_date,
        "last_tx_date":         last_tx_date,
        "months_active":        months_active,
        "top_chatters":         top_chatters,
        "by_model":             by_model,
        "expenses_by_category": expenses_by_category,
    }


async def _monthly_series(db: AsyncSession, tenant_id: int) -> list[dict]:
    """One row per calendar month where there were any transactions OR expenses."""
    tx_r = await db.execute(
        text(
            """SELECT TO_CHAR(date, 'YYYY-MM') AS month,
                      COALESCE(SUM(amount), 0)  AS revenue
               FROM transactions
               WHERE tenant_id = :tid AND date IS NOT NULL
               GROUP BY TO_CHAR(date, 'YYYY-MM')"""
        ),
        {"tid": tenant_id},
    )
    tx_map: dict[str, float] = {
        r["month"]: float(r["revenue"] or 0) for r in tx_r.mappings()
    }

    exp_r = await db.execute(
        text(
            """SELECT TO_CHAR(date, 'YYYY-MM') AS month,
                      COALESCE(SUM(amount), 0)  AS expenses
               FROM expenses
               WHERE tenant_id = :tid AND date IS NOT NULL
               GROUP BY TO_CHAR(date, 'YYYY-MM')"""
        ),
        {"tid": tenant_id},
    )
    exp_map: dict[str, float] = {
        r["month"]: float(r["expenses"] or 0) for r in exp_r.mappings()
    }

    all_months = sorted(set(tx_map) | set(exp_map))
    series = []
    for m in all_months:
        rev  = round(tx_map.get(m, 0.0), 2)
        exp  = round(exp_map.get(m, 0.0), 2)
        prof = round(rev - exp, 2)
        series.append({"month": m, "revenue": rev, "expenses": exp, "profit": prof})
    return series


_MAX_DETAIL_MONTHS = 18


async def _monthly_detail(
    db: AsyncSession,
    tenant_id: int,
    months: list[str],
) -> list[dict]:
    """
    Per-month breakdown (chatters / models / shifts) for the given month list.
    Uses 4 bulk queries (no N×4 round-trips).
    months: sorted list of 'YYYY-MM' strings.
    """
    if not months:
        return []

    # Cutoff date = first day of the earliest month in the list
    cutoff_str = months[0] + "-01"
    months_set  = set(months)

    # ── Revenue + expense totals per month ────────────────────────────────────
    tx_tot_r = await db.execute(
        text(
            """SELECT TO_CHAR(date, 'YYYY-MM') AS month,
                      COALESCE(SUM(amount), 0)  AS revenue
               FROM transactions
               WHERE tenant_id = :tid AND date >= :cutoff
               GROUP BY TO_CHAR(date, 'YYYY-MM')"""
        ),
        {"tid": tenant_id, "cutoff": cutoff_str},
    )
    rev_map: dict[str, float] = {
        r["month"]: float(r["revenue"] or 0)
        for r in tx_tot_r.mappings()
        if r["month"] in months_set
    }

    exp_tot_r = await db.execute(
        text(
            """SELECT TO_CHAR(date, 'YYYY-MM') AS month,
                      COALESCE(SUM(amount), 0)  AS expenses
               FROM expenses
               WHERE tenant_id = :tid AND date >= :cutoff
               GROUP BY TO_CHAR(date, 'YYYY-MM')"""
        ),
        {"tid": tenant_id, "cutoff": cutoff_str},
    )
    exp_map: dict[str, float] = {
        r["month"]: float(r["expenses"] or 0)
        for r in exp_tot_r.mappings()
        if r["month"] in months_set
    }

    # ── Top-10 chatters per month (window function) ───────────────────────────
    top_chat_r = await db.execute(
        text(
            """SELECT month, chatter, revenue, tx_count FROM (
                 SELECT TO_CHAR(t.date, 'YYYY-MM')                         AS month,
                        COALESCE(c.name, t.chatter, '(неизвестен)')        AS chatter,
                        COALESCE(SUM(t.amount), 0)                         AS revenue,
                        COUNT(t.id)                                         AS tx_count,
                        ROW_NUMBER() OVER (
                          PARTITION BY TO_CHAR(t.date, 'YYYY-MM')
                          ORDER BY SUM(t.amount) DESC
                        )                                                   AS rn
                 FROM transactions t
                 LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = :tid
                 WHERE t.tenant_id = :tid
                   AND t.date >= :cutoff
                   AND (t.chatter_id IS NOT NULL OR t.chatter IS NOT NULL)
                 GROUP BY TO_CHAR(t.date, 'YYYY-MM'),
                          COALESCE(c.name, t.chatter, '(неизвестен)')
               ) sub
               WHERE rn <= 10
               ORDER BY month, rn"""
        ),
        {"tid": tenant_id, "cutoff": cutoff_str},
    )
    chatters_by_month: dict[str, list] = defaultdict(list)
    for r in top_chat_r.mappings():
        if r["month"] in months_set:
            chatters_by_month[r["month"]].append({
                "chatter":  r["chatter"],
                "revenue":  round(float(r["revenue"] or 0), 2),
                "tx_count": int(r["tx_count"] or 0),
            })

    # ── By model per month ────────────────────────────────────────────────────
    model_r = await db.execute(
        text(
            """SELECT TO_CHAR(t.date, 'YYYY-MM')                       AS month,
                      COALESCE(mo.name, t.model, '(без модели)')        AS model,
                      COALESCE(SUM(t.amount), 0)                        AS revenue
               FROM transactions t
               LEFT JOIN models mo ON mo.id = t.model_id AND mo.tenant_id = :tid
               WHERE t.tenant_id = :tid AND t.date >= :cutoff
               GROUP BY TO_CHAR(t.date, 'YYYY-MM'),
                        COALESCE(mo.name, t.model, '(без модели)')
               ORDER BY month, revenue DESC"""
        ),
        {"tid": tenant_id, "cutoff": cutoff_str},
    )
    models_by_month: dict[str, list] = defaultdict(list)
    for r in model_r.mappings():
        if r["month"] in months_set:
            models_by_month[r["month"]].append({
                "model":   r["model"],
                "revenue": round(float(r["revenue"] or 0), 2),
            })

    # ── By shift per month ────────────────────────────────────────────────────
    shift_r = await db.execute(
        text(
            """SELECT TO_CHAR(t.date, 'YYYY-MM')                           AS month,
                      COALESCE(sc.name, t.shift_name, '(без смены)')       AS shift,
                      COALESCE(SUM(t.amount), 0)                            AS revenue,
                      COUNT(t.id)                                            AS tx_count
               FROM transactions t
               LEFT JOIN shifts_catalog sc ON sc.id = t.shift_catalog_id AND sc.tenant_id = :tid
               WHERE t.tenant_id = :tid AND t.date >= :cutoff
               GROUP BY TO_CHAR(t.date, 'YYYY-MM'),
                        COALESCE(sc.name, t.shift_name, '(без смены)')
               ORDER BY month, revenue DESC"""
        ),
        {"tid": tenant_id, "cutoff": cutoff_str},
    )
    shifts_by_month: dict[str, list] = defaultdict(list)
    for r in shift_r.mappings():
        if r["month"] in months_set:
            shifts_by_month[r["month"]].append({
                "shift":    r["shift"],
                "revenue":  round(float(r["revenue"] or 0), 2),
                "tx_count": int(r["tx_count"] or 0),
            })

    # ── Assemble ──────────────────────────────────────────────────────────────
    result = []
    for m in months:
        rev  = round(rev_map.get(m, 0.0), 2)
        exp  = round(exp_map.get(m, 0.0), 2)
        result.append({
            "month":        m,
            "revenue":      rev,
            "expenses":     exp,
            "profit":       round(rev - exp, 2),
            "top_chatters": chatters_by_month.get(m, []),
            "by_model":     models_by_month.get(m, []),
            "by_shift":     shifts_by_month.get(m, []),
        })
    return result


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

    # ── By model: revenue + plan (focus month) ────────────────────────────────
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
            "model":               model,
            "revenue":             revenue,
            "plan":                round(plan, 2) if plan else None,
            "plan_completion_pct": pct,
        })

    # ── By shift (focus month) ────────────────────────────────────────────────
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

    # ── Top chatters by chatter_id JOIN catalog (focus month) ─────────────────
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

    # ── Expenses by category (focus month) ───────────────────────────────────
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

    # ── All-time aggregates ───────────────────────────────────────────────────
    all_time = await _all_time(db, tenant_id)

    # ── Monthly series (full history) ─────────────────────────────────────────
    monthly_series = await _monthly_series(db, tenant_id)

    # ── Monthly detail: last ≤18 months with transactions ────────────────────
    tx_months_r = await db.execute(
        text(
            "SELECT DISTINCT TO_CHAR(date, 'YYYY-MM') AS month "
            "FROM transactions WHERE tenant_id=:tid AND date IS NOT NULL "
            "ORDER BY month"
        ),
        {"tid": tenant_id},
    )
    all_tx_months = [r["month"] for r in tx_months_r.mappings()]
    detail_months = all_tx_months[-_MAX_DETAIL_MONTHS:]
    monthly_detail = await _monthly_detail(db, tenant_id, detail_months)

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
        "all_time":             all_time,
        "monthly_series":       monthly_series,
        "monthly_detail":       monthly_detail,
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def _f(v: float | None, prefix: str = "$") -> str:
    """Format a dollar value, or 'нет данных'."""
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

    # ── 1. ALL-TIME ───────────────────────────────────────────────────────────
    at = snapshot.get("all_time") or {}
    lines.append("=== ЗА ВСЁ ВРЕМЯ ===")
    if at:
        first = at.get("first_tx_date") or "нет данных"
        last  = at.get("last_tx_date")  or "нет данных"
        lines.append(f"  Период работы: {first} → {last}")
        lines.append(f"  Активных месяцев: {at.get('months_active', 0)}")
        lines.append(f"  Транзакций: {at.get('total_tx_count', 0)}")
        lines.append(f"  Выручка:  {_f(at.get('revenue'))}")
        lines.append(f"  Расходы:  {_f(at.get('expenses'))}")
        lines.append(f"  Прибыль:  {_f(at.get('profit'))}")
        lines.append(f"  Маржа:    {at.get('margin_pct', 0)}%")

        at_top = at.get("top_chatters") or []
        lines.append("  Топ чаттеров за всё время:")
        if at_top:
            for i, c in enumerate(at_top, 1):
                lines.append(f"    {i}. {c['chatter']}: {_f(c['revenue'])} ({c['tx_count']} тр.)")
        else:
            lines.append("    нет данных")

        at_models = at.get("by_model") or []
        lines.append("  Выручка по моделям (всё время):")
        if at_models:
            for m in at_models:
                lines.append(f"    {m['model']}: {_f(m['revenue'])}")
        else:
            lines.append("    нет данных")

        at_cats = at.get("expenses_by_category") or []
        lines.append("  Расходы по категориям (всё время):")
        if at_cats:
            for e in at_cats:
                lines.append(f"    {e['category']}: {_f(e['amount'])}")
        else:
            lines.append("    нет данных")
    else:
        lines.append("  нет данных")

    # ── 2. MONTHLY SERIES ─────────────────────────────────────────────────────
    series = snapshot.get("monthly_series") or []
    lines.append("\n=== ПОМЕСЯЧНАЯ ДИНАМИКА ===")
    if series:
        lines.append("  Месяц       Выручка         Расходы         Прибыль")
        lines.append("  " + "-" * 60)
        for row in series:
            lines.append(
                f"  {row['month']}    "
                f"{_f(row['revenue']):>15}  "
                f"{_f(row['expenses']):>15}  "
                f"{_f(row['profit']):>15}"
            )
    else:
        lines.append("  нет данных")

    # ── 3. MONTHLY DETAIL ────────────────────────────────────────────────────
    detail = snapshot.get("monthly_detail") or []
    lines.append("\n=== ДЕТАЛИЗАЦИЯ ПО МЕСЯЦАМ ===")
    if detail:
        for md in detail:
            m = md["month"]
            lines.append(f"\n  [{m}]  выручка {_f(md['revenue'])}  расходы {_f(md['expenses'])}  прибыль {_f(md['profit'])}")

            md_top = md.get("top_chatters") or []
            if md_top:
                lines.append("    Чаттеры: " + "  |  ".join(
                    f"{c['chatter']}: {_f(c['revenue'])} ({c['tx_count']} тр.)"
                    for c in md_top
                ))
            else:
                lines.append("    Чаттеры: нет данных")

            md_models = md.get("by_model") or []
            if md_models:
                lines.append("    Модели:  " + "  |  ".join(
                    f"{m_['model']}: {_f(m_['revenue'])}" for m_ in md_models
                ))
            else:
                lines.append("    Модели:  нет данных")

            md_shifts = md.get("by_shift") or []
            if md_shifts:
                lines.append("    Смены:   " + "  |  ".join(
                    f"{s['shift']}: {_f(s['revenue'])} ({s['tx_count']} тр.)"
                    for s in md_shifts
                ))
            else:
                lines.append("    Смены:   нет данных")
    else:
        lines.append("  нет данных")

    # ── 4. FOCUS MONTH ────────────────────────────────────────────────────────
    period      = snapshot.get("period", "")
    period_prev = snapshot.get("period_prev", "")
    t  = snapshot.get("totals", {})
    tp = snapshot.get("totals_prev", {})
    d  = snapshot.get("deltas", {})

    lines.append(f"\n=== ФОКУСНЫЙ МЕСЯЦ ({period}) + сравнение с предыдущим ({period_prev}) ===")
    lines.append("  Финансовое резюме:")
    lines.append(f"    Выручка:  {_f(t.get('revenue'))}{_delta(d.get('revenue_pct'))}")
    lines.append(f"    Расходы:  {_f(t.get('expenses'))}")
    lines.append(f"    Прибыль:  {_f(t.get('profit'))}{_delta(d.get('profit_pct'))}")
    lines.append(f"    Маржа:    {t.get('margin_pct', 0)}%")
    lines.append(f"    Пред. мес.: выручка {_f(tp.get('revenue'))}, прибыль {_f(tp.get('profit'))}")

    by_model = snapshot.get("by_model") or []
    lines.append("  Выручка по моделям:")
    if by_model:
        for m in by_model:
            plan_str = (
                f", план {_f(m['plan'])} → {m['plan_completion_pct']}%"
                if m.get("plan") else ", план не задан"
            )
            lines.append(f"    {m['model']}: {_f(m['revenue'])}{plan_str}")
    else:
        lines.append("    нет данных")

    by_shift = snapshot.get("by_shift") or []
    lines.append("  Выручка по сменам:")
    if by_shift:
        for s in by_shift:
            lines.append(f"    {s['shift']}: {_f(s['revenue'])} ({s['tx_count']} тр.)")
    else:
        lines.append("    нет данных")

    top = snapshot.get("top_chatters") or []
    lines.append("  Топ чаттеров:")
    if top:
        for i, c in enumerate(top, 1):
            lines.append(f"    {i}. {c['chatter']}: {_f(c['revenue'])} ({c['tx_count']} тр.)")
    else:
        lines.append("    нет данных")

    cats = snapshot.get("expenses_by_category") or []
    lines.append("  Расходы по категориям:")
    if cats:
        for e in cats:
            lines.append(f"    {e['category']}: {_f(e['amount'])}")
    else:
        lines.append("    нет данных")

    return "\n".join(lines)
