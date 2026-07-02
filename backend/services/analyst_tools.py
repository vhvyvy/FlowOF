"""Read-only analyst tools for the agentic AI loop.

Each tool is `async def tool(db, tenant_id, **params) -> dict | list`.
tenant_id is ALWAYS injected by the server — never exposed in input_schema.

INVARIANTS (from spec):
  - No raw SQL from the model — only fixed parametrised functions.
  - Read-only on production data.
  - tenant_id never travels through the model layer.
"""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.analyst_tools")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_range(year: int, month: int) -> tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _norm_chatter_name(raw: str) -> str:
    """Canonical form used for matching: strip whitespace, strip leading '@', lowercase.
    Mirrors the logic in schema_patch._norm_name / catalog_resolver.
    """
    return raw.strip().lstrip('@').strip().lower()


# SQL expression that normalises a stored name the same way.
# Usage: WHERE _SQL_NORM_NAME_EXPR('some_col') = :norm_name
_SQL_NORM_CHATTER = "LOWER(TRIM(LEADING '@' FROM TRIM(COALESCE({col}, ''))))"


async def resolve_chatter_for_tools(
    db: AsyncSession,
    tenant_id: int,
    chatter_name: str,
) -> tuple[int | None, str | None]:
    """Return (chatter_id, canonical_display_name) for a name string.

    Matching is tolerant of leading '@', case, and surrounding whitespace.
    Returns (None, None) if no matching chatter is found at all.
    First tries the chatters catalog, then falls back to transaction text field.
    """
    norm = _norm_chatter_name(chatter_name)

    # 1. Try catalog lookup
    cat_row = (await db.execute(
        text(
            f"""
            SELECT id, name FROM chatters
            WHERE tenant_id = :tid
              AND {_SQL_NORM_CHATTER.format(col='name')} = :norm
            ORDER BY active DESC NULLS LAST, id
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "norm": norm},
    )).fetchone()

    if cat_row:
        return int(cat_row[0]), str(cat_row[1])

    # 2. Fallback: check transaction text column (legacy rows without FK)
    tx_row = (await db.execute(
        text(
            f"""
            SELECT DISTINCT t.chatter
            FROM transactions t
            WHERE t.tenant_id = :tid
              AND {_SQL_NORM_CHATTER.format(col='t.chatter')} = :norm
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "norm": norm},
    )).fetchone()

    if tx_row:
        return None, str(tx_row[0])   # chatter_id unknown, but name found

    return None, None


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _pct(current: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return round((current - prev) / abs(prev) * 100, 1)


# ── Tool implementations ───────────────────────────────────────────────────────

async def get_agency_summary(
    db: AsyncSession,
    tenant_id: int,
    *,
    year: int,
    month: int,
) -> dict:
    """Revenue, expenses, profit, margin for a month + MoM comparison."""
    start, end = _month_range(year, month)
    py, pm = _prev_month(year, month)
    pstart, pend = _month_range(py, pm)

    async def _fetch(s: date, e: date) -> tuple[float, float, int]:
        rev = float((await db.execute(
            text("SELECT COALESCE(SUM(amount),0) FROM transactions"
                 " WHERE tenant_id=:tid AND date>=:s AND date<=:e"),
            {"tid": tenant_id, "s": s, "e": e},
        )).scalar() or 0)
        exp = float((await db.execute(
            text("SELECT COALESCE(SUM(amount),0) FROM expenses"
                 " WHERE tenant_id=:tid AND date>=:s AND date<=:e"),
            {"tid": tenant_id, "s": s, "e": e},
        )).scalar() or 0)
        cnt = int((await db.execute(
            text("SELECT COUNT(*) FROM transactions"
                 " WHERE tenant_id=:tid AND date>=:s AND date<=:e"),
            {"tid": tenant_id, "s": s, "e": e},
        )).scalar() or 0)
        return rev, exp, cnt

    rev, exp, cnt   = await _fetch(start, end)
    prev_rev, prev_exp, _ = await _fetch(pstart, pend)
    profit      = rev - exp
    prev_profit = prev_rev - prev_exp
    margin      = round(profit / rev * 100, 1) if rev > 0 else 0.0

    return {
        "period":     f"{month:02d}/{year}",
        "revenue":    round(rev, 2),
        "expenses":   round(exp, 2),
        "profit":     round(profit, 2),
        "margin_pct": margin,
        "tx_count":   cnt,
        "vs_prev": {
            "period":      f"{pm:02d}/{py}",
            "revenue_pct": _pct(rev, prev_rev),
            "profit_pct":  _pct(profit, prev_profit),
            "prev_revenue": round(prev_rev, 2),
            "prev_profit":  round(prev_profit, 2),
        },
    }


async def get_monthly_trend(
    db: AsyncSession,
    tenant_id: int,
) -> list[dict]:
    """Full month-by-month revenue / expenses / profit series (all history)."""
    rows = (await db.execute(
        text(
            """
            SELECT
                TO_CHAR(DATE_TRUNC('month', d), 'YYYY-MM') AS month,
                COALESCE(SUM(rev), 0)                       AS revenue,
                COALESCE(SUM(exp), 0)                       AS expenses
            FROM (
                SELECT DATE_TRUNC('month', date) AS d, amount AS rev, 0 AS exp
                FROM transactions WHERE tenant_id = :tid AND date IS NOT NULL
                UNION ALL
                SELECT DATE_TRUNC('month', date) AS d, 0 AS rev, amount AS exp
                FROM expenses WHERE tenant_id = :tid AND date IS NOT NULL
            ) x
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"tid": tenant_id},
    )).fetchall()

    result = []
    for r in rows:
        rev = float(r[1] or 0)
        exp = float(r[2] or 0)
        result.append({
            "month":    r[0],
            "revenue":  round(rev, 2),
            "expenses": round(exp, 2),
            "profit":   round(rev - exp, 2),
        })
    return result


async def get_top_chatters(
    db: AsyncSession,
    tenant_id: int,
    *,
    year: int,
    month: int,
    limit: int = 10,
) -> list[dict]:
    """Top chatters by revenue for a given month."""
    start, end = _month_range(year, month)
    rows = (await db.execute(
        text(
            """
            SELECT
                COALESCE(c.name, t.chatter, '(без чаттера)') AS chatter,
                SUM(t.amount)  AS revenue,
                COUNT(t.id)    AS tx_count
            FROM transactions t
            LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = t.tenant_id
            WHERE t.tenant_id = :tid AND t.date >= :s AND t.date <= :e
            GROUP BY 1
            ORDER BY revenue DESC
            LIMIT :lim
            """
        ),
        {"tid": tenant_id, "s": start, "e": end, "lim": limit},
    )).fetchall()

    return [
        {
            "rank":     i + 1,
            "chatter":  r[0],
            "revenue":  round(float(r[1] or 0), 2),
            "tx_count": int(r[2] or 0),
        }
        for i, r in enumerate(rows)
    ]


async def get_chatter_detail(
    db: AsyncSession,
    tenant_id: int,
    *,
    chatter_name: str,
    months_back: int = 6,
) -> dict:
    """Month-by-month revenue history for a specific chatter.

    Matching is tolerant of '@' prefix, case, and whitespace.
    Falls back to full history if the chatter has no activity in the
    requested window but does exist elsewhere in the database.
    """
    # ── Resolve chatter (tolerant name matching) ─────────────────────────────
    chatter_id, canonical_name = await resolve_chatter_for_tools(db, tenant_id, chatter_name)

    if chatter_id is None and canonical_name is None:
        return {"chatter": chatter_name, "found": False, "history": []}

    display_name = canonical_name or chatter_name

    # ── Build WHERE predicate using resolved identity ─────────────────────────
    # Match by chatter_id (FK) if available, AND/OR by normalised text fields.
    norm = _norm_chatter_name(chatter_name)
    id_clause = ""
    params: dict[str, Any] = {"tid": tenant_id, "norm": norm}

    if chatter_id is not None:
        id_clause = "OR t.chatter_id = :cid"
        params["cid"] = chatter_id

    name_match_sql = f"""(
        {_SQL_NORM_CHATTER.format(col='COALESCE(c.name, t.chatter)')} = :norm
        {id_clause}
    )"""

    # ── Cutoff date ───────────────────────────────────────────────────────────
    def _months_ago(n: int) -> date:
        today = date.today()
        m = today.month - n
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        return date(y, m, 1)

    cutoff = _months_ago(months_back)

    # ── Query ─────────────────────────────────────────────────────────────────
    base_sql = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('month', t.date), 'YYYY-MM') AS month,
            SUM(t.amount)  AS revenue,
            COUNT(t.id)    AS tx_count
        FROM transactions t
        LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = t.tenant_id
        WHERE t.tenant_id = :tid
          AND {name_match_sql}
          AND t.date >= :cutoff
        GROUP BY 1
        ORDER BY 1 DESC
    """
    rows = (await db.execute(text(base_sql), {**params, "cutoff": cutoff})).fetchall()

    # If nothing found within window, expand to full history (chatter may be inactive)
    if not rows:
        all_sql = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', t.date), 'YYYY-MM') AS month,
                SUM(t.amount)  AS revenue,
                COUNT(t.id)    AS tx_count
            FROM transactions t
            LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = t.tenant_id
            WHERE t.tenant_id = :tid
              AND {name_match_sql}
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 36
        """
        rows = (await db.execute(text(all_sql), params)).fetchall()

    if not rows:
        return {"chatter": display_name, "found": False, "history": [],
                "note": f"Чаттер '{display_name}' найден в справочнике, но транзакций нет."}

    history = [
        {
            "month":    r[0],
            "revenue":  round(float(r[1] or 0), 2),
            "tx_count": int(r[2] or 0),
        }
        for r in rows
    ]
    revenues = [h["revenue"] for h in history if h["revenue"] > 0]
    avg = round(sum(revenues) / len(revenues), 2) if revenues else 0.0
    trend = "нет данных"
    if len(revenues) >= 2:
        trend = "рост" if revenues[0] > revenues[-1] else "снижение"

    return {
        "chatter":             display_name,
        "found":               True,
        "months_shown":        len(history),
        "avg_monthly_revenue": avg,
        "trend":               trend,
        "history":             history,
    }


async def get_chatter_kpi_tool(
    db: AsyncSession,
    tenant_id: int,
    *,
    year: int,
    month: int,
) -> list[dict]:
    """KPI metrics for all chatters in a month (from kpi_service)."""
    from services.kpi_service import get_chatter_kpi

    rows, _rev, _txns, _rpc = await get_chatter_kpi(db, tenant_id, year, month)
    result = []
    for r in rows:
        entry: dict[str, Any] = {
            "chatter":       r.chatter,
            "revenue":       round(float(r.revenue or 0), 2),
            "total_chats":   r.total_chats,
            "rpc":           round(float(r.rpc), 2) if r.rpc is not None else None,
            "ppv_open_rate": round(float(r.ppv_open_rate), 1) if r.ppv_open_rate is not None else None,
            "revenue_delta": round(float(r.revenue_delta), 1) if r.revenue_delta is not None else None,
        }
        result.append(entry)
    return result


async def get_model_performance(
    db: AsyncSession,
    tenant_id: int,
    *,
    year: int,
    month: int,
) -> list[dict]:
    """Revenue per model for a month, with plan and completion % where available."""
    start, end = _month_range(year, month)

    rows = (await db.execute(
        text(
            """
            SELECT
                COALESCE(m.name, t.model, '(без модели)') AS model,
                SUM(t.amount)  AS revenue,
                COUNT(t.id)    AS tx_count
            FROM transactions t
            LEFT JOIN models m ON m.id = t.model_id AND m.tenant_id = t.tenant_id
            WHERE t.tenant_id = :tid AND t.date >= :s AND t.date <= :e
            GROUP BY 1
            ORDER BY revenue DESC
            """
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )).fetchall()

    # plans.model is a plain text column matching models.name (no model_id FK)
    plans = (await db.execute(
        text(
            """
            SELECT p.model, p.plan_amount
            FROM plans p
            WHERE p.tenant_id = :tid AND p.year = :y AND p.month = :mo
            """
        ),
        {"tid": tenant_id, "y": year, "mo": month},
    )).fetchall()
    plan_map = {r[0]: float(r[1] or 0) for r in plans}

    result = []
    for r in rows:
        model   = r[0]
        revenue = round(float(r[1] or 0), 2)
        plan    = plan_map.get(model)
        result.append({
            "model":          model,
            "revenue":        revenue,
            "tx_count":       int(r[2] or 0),
            "plan":           round(plan, 2) if plan is not None else None,
            "completion_pct": round(revenue / plan * 100, 1) if plan else None,
        })
    return result


async def get_shift_breakdown(
    db: AsyncSession,
    tenant_id: int,
    *,
    year: int,
    month: int,
) -> list[dict]:
    """Revenue and transaction count per shift for a month."""
    start, end = _month_range(year, month)

    rows = (await db.execute(
        text(
            """
            SELECT
                COALESCE(sc.name, t.shift_name, '(без смены)') AS shift,
                SUM(t.amount)  AS revenue,
                COUNT(t.id)    AS tx_count
            FROM transactions t
            LEFT JOIN shifts_catalog sc
                   ON sc.id = t.shift_catalog_id AND sc.tenant_id = t.tenant_id
            WHERE t.tenant_id = :tid AND t.date >= :s AND t.date <= :e
            GROUP BY 1
            ORDER BY revenue DESC
            """
        ),
        {"tid": tenant_id, "s": start, "e": end},
    )).fetchall()

    return [
        {
            "shift":    r[0],
            "revenue":  round(float(r[1] or 0), 2),
            "tx_count": int(r[2] or 0),
        }
        for r in rows
    ]


# Allowed group_by values → SQL expression (NO raw user SQL)
_GROUP_BY_EXPRS: dict[str, str] = {
    "day_of_week": "TO_CHAR(date, 'Day')",
    "model":       "COALESCE(t.model, '(без модели)')",
    "chatter":     "COALESCE(t.chatter, '(без чаттера)')",
    "shift":       "COALESCE(t.shift_name, '(без смены)')",
    "date":        "t.date::text",
}


async def query_transactions_flexible(
    db: AsyncSession,
    tenant_id: int,
    *,
    group_by: str,
    date_from: str,
    date_to: str,
    filter_model: str | None = None,
    filter_chatter: str | None = None,
    filter_shift: str | None = None,
) -> list[dict]:
    """Flexible aggregation of transactions.

    group_by must be one of: day_of_week, model, chatter, shift, date.
    date_from / date_to: ISO strings YYYY-MM-DD.
    """
    if group_by not in _GROUP_BY_EXPRS:
        return [{"error": f"group_by '{group_by}' не поддерживается. "
                          f"Допустимые значения: {', '.join(_GROUP_BY_EXPRS)}"}]

    try:
        d_from = date.fromisoformat(date_from)
        d_to   = date.fromisoformat(date_to)
    except ValueError:
        return [{"error": "Неверный формат даты. Используй YYYY-MM-DD."}]

    expr   = _GROUP_BY_EXPRS[group_by]
    params: dict[str, Any] = {"tid": tenant_id, "df": d_from, "dt": d_to}

    filters = "AND t.tenant_id = :tid AND t.date >= :df AND t.date <= :dt"
    if filter_model:
        filters += " AND LOWER(COALESCE(t.model, '')) = LOWER(:fmodel)"
        params["fmodel"] = filter_model
    if filter_chatter:
        filters += " AND LOWER(COALESCE(t.chatter, '')) = LOWER(:fchatter)"
        params["fchatter"] = filter_chatter
    if filter_shift:
        filters += " AND LOWER(COALESCE(t.shift_name, '')) = LOWER(:fshift)"
        params["fshift"] = filter_shift

    rows = (await db.execute(
        text(
            f"""
            SELECT {expr} AS grp,
                   SUM(t.amount)  AS revenue,
                   COUNT(t.id)    AS tx_count
            FROM transactions t
            WHERE 1=1 {filters}
            GROUP BY 1
            ORDER BY revenue DESC
            LIMIT 100
            """
        ),
        params,
    )).fetchall()

    return [
        {
            "group":    str(r[0]).strip() if r[0] is not None else "(пусто)",
            "revenue":  round(float(r[1] or 0), 2),
            "tx_count": int(r[2] or 0),
        }
        for r in rows
    ]


async def find_anomalies(
    db: AsyncSession,
    tenant_id: int,
    *,
    year: int,
    month: int,
) -> list[dict]:
    """Detect anomalies: revenue drops >30%, low RPC with high chats, model concentration risk."""
    start, end = _month_range(year, month)
    py, pm     = _prev_month(year, month)
    pstart, pend = _month_range(py, pm)

    anomalies: list[dict] = []

    # ── 1. Chatters with revenue drop > 30% ──────────────────────────────────
    curr_rows = {
        r[0]: float(r[1] or 0)
        for r in (await db.execute(
            text(
                """
                SELECT COALESCE(c.name, t.chatter) AS ch, SUM(t.amount)
                FROM transactions t
                LEFT JOIN chatters c ON c.id=t.chatter_id AND c.tenant_id=t.tenant_id
                WHERE t.tenant_id=:tid AND t.date>=:s AND t.date<=:e
                  AND t.chatter IS NOT NULL
                GROUP BY 1
                """
            ),
            {"tid": tenant_id, "s": start, "e": end},
        )).fetchall()
    }
    prev_rows = {
        r[0]: float(r[1] or 0)
        for r in (await db.execute(
            text(
                """
                SELECT COALESCE(c.name, t.chatter) AS ch, SUM(t.amount)
                FROM transactions t
                LEFT JOIN chatters c ON c.id=t.chatter_id AND c.tenant_id=t.tenant_id
                WHERE t.tenant_id=:tid AND t.date>=:s AND t.date<=:e
                  AND t.chatter IS NOT NULL
                GROUP BY 1
                """
            ),
            {"tid": tenant_id, "s": pstart, "e": pend},
        )).fetchall()
    }

    for chatter, rev in curr_rows.items():
        prev_rev = prev_rows.get(chatter, 0)
        if prev_rev > 0:
            delta = _pct(rev, prev_rev)
            if delta is not None and delta <= -30:
                anomalies.append({
                    "type":       "revenue_drop",
                    "entity":     chatter,
                    "current":    round(rev, 2),
                    "prev":       round(prev_rev, 2),
                    "delta_pct":  delta,
                    "severity":   "high" if delta <= -50 else "medium",
                    "message":    (
                        f"{chatter}: выручка упала на {abs(delta):.0f}% "
                        f"(${prev_rev:,.0f} → ${rev:,.0f})"
                    ),
                })

    # ── 2. KPI: low RPC with high chat volume ─────────────────────────────────
    try:
        from services.kpi_service import get_chatter_kpi
        kpi_rows, _tr, _tt, median_rpc = await get_chatter_kpi(db, tenant_id, year, month)
        rpc_threshold = (median_rpc or 0) * 0.5  # below half the agency median

        all_chats = [r.total_chats or 0 for r in kpi_rows if r.total_chats]
        median_chats = sorted(all_chats)[len(all_chats) // 2] if all_chats else 0

        for r in kpi_rows:
            if (
                r.rpc is not None
                and r.total_chats
                and r.rpc < rpc_threshold
                and r.total_chats > median_chats
            ):
                anomalies.append({
                    "type":     "low_rpc",
                    "entity":   r.chatter,
                    "rpc":      round(float(r.rpc), 3),
                    "chats":    r.total_chats,
                    "severity": "medium",
                    "message":  (
                        f"{r.chatter}: низкий RPC {r.rpc:.3f} при {r.total_chats} чатах "
                        f"(медиана агентства {median_rpc:.3f if median_rpc else '—'})"
                    ),
                })
    except Exception as e:
        logger.debug("find_anomalies: KPI unavailable: %s", e)

    # ── 3. Model concentration risk ───────────────────────────────────────────
    model_rows = await get_model_performance(db, tenant_id, year=year, month=month)
    total_rev  = sum(m["revenue"] for m in model_rows)
    if total_rev > 0 and len(model_rows) >= 3:
        top3_rev  = sum(m["revenue"] for m in model_rows[:3])
        top3_share = round(top3_rev / total_rev * 100, 1)
        if top3_share > 80:
            top3_names = ", ".join(m["model"] for m in model_rows[:3])
            anomalies.append({
                "type":          "model_concentration",
                "top3_share_pct": top3_share,
                "top3_models":   top3_names,
                "severity":      "medium",
                "message":       (
                    f"Высокая концентрация: топ-3 модели ({top3_names}) "
                    f"дают {top3_share}% выручки — риск при потере одной модели"
                ),
            })

    if not anomalies:
        return [{"type": "none", "message": "Явных аномалий не обнаружено."}]
    return anomalies


# ── WRITE tools — agent memory layer (agent_events table) ────────────────────

_OPEN_STATUSES = ("proposed", "accepted", "in_progress", "review_due")
_CLOSED_STATUSES = ("closed_success", "closed_failed", "dismissed")
_ALL_STATUSES = _OPEN_STATUSES + _CLOSED_STATUSES


async def create_event(
    db: AsyncSession,
    tenant_id: int,
    *,
    title: str,
    description: str = "",
    entity_type: str | None = None,
    entity_ref: str | None = None,
    trigger_metric: str | None = None,
    trigger_value_before: float | None = None,
    review_in_days: int | None = None,
    source: str = "chat",
    priority: str = "normal",
) -> dict:
    """Create an agent event (memory entry).

    Hybrid rule:
      source='chat'    → status='proposed'  (needs owner confirmation)
      source='watcher' → status='accepted'  (auto-created by anomaly detection)
      source='user'    → status='accepted'  (owner initiated)
    """
    from models import AgentEvent

    status = "proposed" if source == "chat" else "accepted"
    review_date = None
    if review_in_days:
        review_date = date.today() + timedelta(days=int(review_in_days))

    ev = AgentEvent(
        tenant_id=tenant_id,
        title=title.strip(),
        description=description.strip() or None,
        entity_type=entity_type,
        entity_ref=entity_ref,
        trigger_metric=trigger_metric,
        trigger_value_before=trigger_value_before,
        status=status,
        source=source,
        created_by="agent",
        priority=priority,
        review_date=review_date,
    )
    db.add(ev)
    await db.flush()  # get id without committing whole session
    await db.commit()
    logger.info("agent create_event id=%s title=%r tenant=%s", ev.id, title[:60], tenant_id)
    return {
        "created": True,
        "event_id": ev.id,
        "status": status,
        "title": ev.title,
        "review_date": review_date.isoformat() if review_date else None,
    }


async def get_open_events(
    db: AsyncSession,
    tenant_id: int,
    *,
    entity_ref: str | None = None,
) -> list[dict]:
    """Return all non-closed events for this tenant (optionally filtered by entity)."""
    from sqlalchemy import text as _text

    params: dict[str, Any] = {"tid": tenant_id}
    extra = ""
    if entity_ref:
        extra = " AND LOWER(entity_ref) = LOWER(:eref)"
        params["eref"] = entity_ref

    rows = (await db.execute(
        _text(
            f"""
            SELECT id, title, description, entity_type, entity_ref,
                   trigger_metric, trigger_value_before,
                   status, source, priority, created_at, review_date
            FROM agent_events
            WHERE tenant_id = :tid
              AND status NOT IN ('closed_success','closed_failed','dismissed')
              {extra}
            ORDER BY
                CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT 50
            """
        ),
        params,
    )).fetchall()

    return [
        {
            "id":                   r[0],
            "title":                r[1],
            "description":          r[2],
            "entity_type":          r[3],
            "entity_ref":           r[4],
            "trigger_metric":       r[5],
            "trigger_value_before": float(r[6]) if r[6] is not None else None,
            "status":               r[7],
            "source":               r[8],
            "priority":             r[9],
            "created_at":           r[10].isoformat() if r[10] else None,
            "review_date":          r[11].isoformat() if r[11] else None,
        }
        for r in rows
    ]


async def update_event_status(
    db: AsyncSession,
    tenant_id: int,
    *,
    event_id: int,
    new_status: str,
    note: str = "",
) -> dict:
    """Update the status of an agent event. Optionally append a note to description."""
    from sqlalchemy import text as _text

    if new_status not in _ALL_STATUSES:
        return {"error": f"Неверный статус '{new_status}'. Допустимые: {', '.join(_ALL_STATUSES)}"}

    # Verify ownership
    row = (await db.execute(
        _text("SELECT id, status FROM agent_events WHERE id=:eid AND tenant_id=:tid"),
        {"eid": event_id, "tid": tenant_id},
    )).fetchone()
    if row is None:
        return {"error": f"Событие id={event_id} не найдено"}

    params: dict[str, Any] = {"eid": event_id, "tid": tenant_id, "status": new_status}
    note_sql = ""
    if note:
        note_sql = ", description = COALESCE(description,'') || E'\\n[' || NOW()::text || '] ' || :note"
        params["note"] = note.strip()

    await db.execute(
        _text(f"UPDATE agent_events SET status=:status {note_sql} WHERE id=:eid AND tenant_id=:tid"),
        params,
    )
    await db.commit()
    return {"updated": True, "event_id": event_id, "new_status": new_status}


async def close_event(
    db: AsyncSession,
    tenant_id: int,
    *,
    event_id: int,
    outcome: str,
    outcome_value_after: float | None = None,
) -> dict:
    """Close an event with a final outcome (success or failed based on outcome text)."""
    from sqlalchemy import text as _text

    row = (await db.execute(
        _text("SELECT id FROM agent_events WHERE id=:eid AND tenant_id=:tid"),
        {"eid": event_id, "tid": tenant_id},
    )).fetchone()
    if row is None:
        return {"error": f"Событие id={event_id} не найдено"}

    # Determine success/failure from outcome keyword hints
    outcome_lower = outcome.lower()
    status = "closed_success" if any(
        w in outcome_lower for w in ("улучш", "вырос", "испрви", "решен", "достиг", "выполн", "success", "+")
    ) else "closed_failed"

    params: dict[str, Any] = {
        "eid": event_id, "tid": tenant_id,
        "status": status, "outcome": outcome.strip(),
    }
    val_sql = ""
    if outcome_value_after is not None:
        val_sql = ", outcome_value_after=:oval"
        params["oval"] = outcome_value_after

    await db.execute(
        _text(
            f"UPDATE agent_events SET status=:status, outcome=:outcome, "
            f"closed_at=NOW() {val_sql} WHERE id=:eid AND tenant_id=:tid"
        ),
        params,
    )
    await db.commit()
    return {"closed": True, "event_id": event_id, "status": status}


# ── Tool registry (name → async callable) ────────────────────────────────────

TOOL_REGISTRY: dict[str, Any] = {
    # READ
    "get_agency_summary":           get_agency_summary,
    "get_monthly_trend":            get_monthly_trend,
    "get_top_chatters":             get_top_chatters,
    "get_chatter_detail":           get_chatter_detail,
    "get_chatter_kpi_tool":         get_chatter_kpi_tool,
    "get_model_performance":        get_model_performance,
    "get_shift_breakdown":          get_shift_breakdown,
    "query_transactions_flexible":  query_transactions_flexible,
    "find_anomalies":               find_anomalies,
    # WRITE (agent memory layer only — not production data)
    "create_event":                 create_event,
    "get_open_events":              get_open_events,
    "update_event_status":          update_event_status,
    "close_event":                  close_event,
}

# ── Anthropic tool descriptions (input_schema NEVER contains tenant_id) ──────

TOOL_DESCRIPTIONS: list[dict] = [
    {
        "name": "get_agency_summary",
        "description": (
            "Ключевые финансовые метрики агентства за указанный месяц: выручка, расходы, прибыль, маржа, "
            "число транзакций, и сравнение с предыдущим месяцем (% изменения). "
            "Используй как отправную точку для любого финансового вопроса."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year":  {"type": "integer", "description": "Год (например 2026)"},
                "month": {"type": "integer", "description": "Месяц 1–12"},
            },
            "required": ["year", "month"],
        },
    },
    {
        "name": "get_monthly_trend",
        "description": (
            "Помесячный ряд выручки / расходов / прибыли за всю историю агентства. "
            "Используй для анализа трендов, поиска лучшего/худшего месяца, сезонности."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_top_chatters",
        "description": (
            "Топ чаттеров по выручке за указанный месяц с числом транзакций. "
            "Используй для вопросов «кто лучший», «кто принёс больше всего»."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer", "description": "Месяц 1–12"},
                "limit": {"type": "integer", "description": "Число чаттеров (по умолчанию 10)", "default": 10},
            },
            "required": ["year", "month"],
        },
    },
    {
        "name": "get_chatter_detail",
        "description": (
            "Помесячная история выручки и транзакций конкретного чаттера. "
            "Используй для анализа динамики одного чаттера, поиска тренда, причины падения."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chatter_name": {
                    "type": "string",
                    "description": "Имя или ник чаттера (поиск без учёта регистра)",
                },
                "months_back": {
                    "type": "integer",
                    "description": "Сколько месяцев истории показать (по умолчанию 6)",
                    "default": 6,
                },
            },
            "required": ["chatter_name"],
        },
    },
    {
        "name": "get_chatter_kpi_tool",
        "description": (
            "KPI-метрики всех чаттеров за месяц: RPC (revenue per chat), PPV Open Rate, "
            "число чатов, изменение выручки к прошлому месяцу. "
            "Используй для анализа эффективности, монетизации, PPV-открываемости."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
    },
    {
        "name": "get_model_performance",
        "description": (
            "Выручка и выполнение плана по каждой модели (OF-аккаунту) за месяц. "
            "Используй для вопросов о том, какая модель принесла больше, или план выполнен."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
    },
    {
        "name": "get_shift_breakdown",
        "description": (
            "Разбивка выручки и транзакций по сменам за месяц. "
            "Используй для вопросов о том, какая смена эффективнее."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
    },
    {
        "name": "query_transactions_flexible",
        "description": (
            "Гибкий срез транзакций с группировкой по выбранному измерению за произвольный период. "
            "group_by: 'day_of_week', 'model', 'chatter', 'shift', 'date'. "
            "Используй для нестандартных вопросов: «какой день недели самый прибыльный», "
            "«выручка по дням», «как работала смена X в феврале»."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["day_of_week", "model", "chatter", "shift", "date"],
                    "description": "Измерение для группировки",
                },
                "date_from": {
                    "type": "string",
                    "description": "Начало периода YYYY-MM-DD",
                },
                "date_to": {
                    "type": "string",
                    "description": "Конец периода YYYY-MM-DD",
                },
                "filter_model":   {"type": "string", "description": "Фильтр по модели (необязательно)"},
                "filter_chatter": {"type": "string", "description": "Фильтр по чаттеру (необязательно)"},
                "filter_shift":   {"type": "string", "description": "Фильтр по смене (необязательно)"},
            },
            "required": ["group_by", "date_from", "date_to"],
        },
    },
    {
        "name": "find_anomalies",
        "description": (
            "Автоматически обнаруживает аномалии за месяц: "
            "падение выручки чаттера >30% к прошлому месяцу; "
            "низкий RPC при высоком объёме чатов; "
            "риск концентрации (топ-3 модели >80% выручки). "
            "Используй при вопросах «есть ли проблемы», «кого надо проверить», «что пошло не так»."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year":  {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
    },
    # ── WRITE tools (memory layer) ────────────────────────────────────────────
    {
        "name": "create_event",
        "description": (
            "Создать событие в памяти агента — зафиксировать аномалию, дать задачу, поставить точку для отслеживания. "
            "Правило гибрида: жёсткую объективную аномалию (данные из инструментов) → создавай сам (source='watcher'). "
            "Субъективный вывод из разговора → НЕ создавай сам, только предлагай (source='chat' → статус proposed). "
            "Всегда проверяй get_open_events перед созданием — не плоди дубли по одному entity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title":                 {"type": "string", "description": "Краткое название задачи/наблюдения"},
                "description":           {"type": "string", "description": "Детальный контекст"},
                "entity_type":           {"type": "string", "enum": ["chatter", "model", "shift", "agency"], "description": "Тип сущности"},
                "entity_ref":            {"type": "string", "description": "Имя/ID сущности (чаттер, модель и т.д.)"},
                "trigger_metric":        {"type": "string", "description": "Метрика-триггер: rpc, revenue_mom, open_rate и т.п."},
                "trigger_value_before":  {"type": "number", "description": "Значение метрики на момент создания"},
                "review_in_days":        {"type": "integer", "description": "Через сколько дней проверить (для review_date)"},
                "source":                {"type": "string", "enum": ["chat", "watcher", "user"], "description": "Источник события"},
                "priority":              {"type": "string", "enum": ["high", "normal", "low"]},
            },
            "required": ["title", "source"],
        },
    },
    {
        "name": "get_open_events",
        "description": (
            "Получить список открытых событий в памяти агента (не закрытых и не отклонённых). "
            "Вызывай в начале ответа, чтобы сверить — есть ли уже открытые дела по теме вопроса. "
            "Если entity_ref указан — фильтрует по сущности (чаттер/модель)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_ref": {"type": "string", "description": "Имя чаттера или модели для фильтрации (необязательно)"},
            },
            "required": [],
        },
    },
    {
        "name": "update_event_status",
        "description": (
            "Обновить статус существующего события. "
            "Переходы: proposed→accepted (принято), accepted→in_progress (взято в работу), "
            "любой→dismissed (закрыто как неактуальное). "
            "Можно добавить заметку."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id":   {"type": "integer", "description": "ID события"},
                "new_status": {
                    "type": "string",
                    "enum": ["proposed", "accepted", "in_progress", "review_due",
                             "closed_success", "closed_failed", "dismissed"],
                },
                "note": {"type": "string", "description": "Необязательная заметка"},
            },
            "required": ["event_id", "new_status"],
        },
    },
    {
        "name": "close_event",
        "description": (
            "Закрыть событие с итогом. "
            "outcome — текст что произошло. "
            "outcome_value_after — значение метрики после (для сравнения с trigger_value_before)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id":           {"type": "integer"},
                "outcome":            {"type": "string", "description": "Текст итога"},
                "outcome_value_after":{"type": "number", "description": "Значение метрики после (необязательно)"},
            },
            "required": ["event_id", "outcome"],
        },
    },
]
