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
    """Month-by-month revenue history for a specific chatter."""
    # Determine the date cutoff
    today = date.today()
    if today.month - months_back > 0:
        cutoff_year, cutoff_month = today.year, today.month - months_back
    else:
        back = months_back - today.month
        cutoff_year  = today.year - 1 - (back // 12)
        cutoff_month = 12 - (back % 12)
        if cutoff_month <= 0:
            cutoff_year  -= 1
            cutoff_month += 12
    cutoff = date(cutoff_year, cutoff_month, 1)

    rows = (await db.execute(
        text(
            """
            SELECT
                TO_CHAR(DATE_TRUNC('month', t.date), 'YYYY-MM') AS month,
                SUM(t.amount)  AS revenue,
                COUNT(t.id)    AS tx_count
            FROM transactions t
            LEFT JOIN chatters c ON c.id = t.chatter_id AND c.tenant_id = t.tenant_id
            WHERE t.tenant_id = :tid
              AND t.date >= :cutoff
              AND (
                  LOWER(COALESCE(c.name, t.chatter, '')) = LOWER(:name)
                  OR LOWER(t.chatter) = LOWER(:name)
              )
            GROUP BY 1
            ORDER BY 1 DESC
            """
        ),
        {"tid": tenant_id, "cutoff": cutoff, "name": chatter_name},
    )).fetchall()

    if not rows:
        return {"chatter": chatter_name, "found": False, "history": []}

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
        "chatter":  chatter_name,
        "found":    True,
        "months_shown": len(history),
        "avg_monthly_revenue": avg,
        "trend":    trend,
        "history":  history,
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

    plans = (await db.execute(
        text(
            """
            SELECT m.name, p.planned_amount
            FROM plans p
            JOIN models m ON m.id = p.model_id
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


# ── Tool registry (name → async callable) ────────────────────────────────────

TOOL_REGISTRY: dict[str, Any] = {
    "get_agency_summary":           get_agency_summary,
    "get_monthly_trend":            get_monthly_trend,
    "get_top_chatters":             get_top_chatters,
    "get_chatter_detail":           get_chatter_detail,
    "get_chatter_kpi_tool":         get_chatter_kpi_tool,
    "get_model_performance":        get_model_performance,
    "get_shift_breakdown":          get_shift_breakdown,
    "query_transactions_flexible":  query_transactions_flexible,
    "find_anomalies":               find_anomalies,
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
]
