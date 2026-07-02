"""Agency profile service — reads/writes the agency 'passport' and builds
the semantic context block that is injected into the LLM system prompt.
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.agency_profile")

# Default thresholds (also stored in schema_patch defaults)
_DEFAULTS: dict[str, Any] = {
    "rpc_critical":       0.15,
    "rpc_working_low":    0.25,
    "rpc_strong":         0.50,
    "open_rate_critical": 20.0,
    "open_rate_working":  25.0,
    "open_rate_strong":   35.0,
    "priorities":         None,
    "glossary":           None,
    "target_notes":       None,
}


async def get_agency_profile(db: AsyncSession, tenant_id: int) -> dict[str, Any]:
    """Return the agency_profile row, creating with defaults if absent."""
    row = (await db.execute(
        text("SELECT * FROM agency_profile WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )).mappings().one_or_none()

    if row is None:
        await db.execute(
            text(
                """INSERT INTO agency_profile (tenant_id)
                   VALUES (:tid)
                   ON CONFLICT (tenant_id) DO NOTHING"""
            ),
            {"tid": tenant_id},
        )
        await db.commit()
        row = (await db.execute(
            text("SELECT * FROM agency_profile WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )).mappings().one_or_none()

    if row is None:
        return {"tenant_id": tenant_id, **_DEFAULTS}

    return dict(row)


async def save_agency_profile(db: AsyncSession, tenant_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """Upsert agency_profile with the given fields. Returns updated row."""
    # Ensure row exists
    await get_agency_profile(db, tenant_id)

    allowed = {
        "rpc_critical", "rpc_working_low", "rpc_strong",
        "open_rate_critical", "open_rate_working", "open_rate_strong",
        "priorities", "glossary", "target_notes",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return await get_agency_profile(db, tenant_id)

    filtered["updated_at"] = datetime.utcnow()
    set_clause = ", ".join(f"{k} = :{k}" for k in filtered)
    filtered["tid"] = tenant_id

    await db.execute(
        text(f"UPDATE agency_profile SET {set_clause} WHERE tenant_id = :tid"),
        filtered,
    )
    await db.commit()
    return await get_agency_profile(db, tenant_id)


async def build_profile_context(db: AsyncSession, tenant_id: int) -> str:
    """Build a compact text 'passport' of the agency for the LLM system prompt.

    Combines:
      - Auto-calculated facts (teams, active chatters, top models, RPC/OpenRate)
      - Owner-defined thresholds, priorities, glossary, goals
    """
    profile = await get_agency_profile(db, tenant_id)

    # ── Auto part ─────────────────────────────────────────────────────────────
    auto_lines: list[str] = []

    try:
        # Number of teams
        teams_r = await db.execute(
            text("SELECT COUNT(*) FROM teams WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        n_teams = teams_r.scalar() or 0
        auto_lines.append(f"Команд: {n_teams}")
    except Exception:
        pass

    try:
        # Active chatters
        chatters_r = await db.execute(
            text("SELECT COUNT(*) FROM chatters WHERE tenant_id = :tid AND active = TRUE"),
            {"tid": tenant_id},
        )
        n_chatters = chatters_r.scalar() or 0
        auto_lines.append(f"Активных чаттеров: {n_chatters}")
    except Exception:
        pass

    try:
        # Agency activity period
        period_r = (await db.execute(
            text(
                "SELECT MIN(date)::text, MAX(date)::text, "
                "COUNT(DISTINCT TO_CHAR(date,'YYYY-MM')) "
                "FROM transactions WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )).fetchone()
        if period_r and period_r[0]:
            first, last, months = period_r
            auto_lines.append(f"Период работы: {first} → {last} ({months} мес.)")
    except Exception:
        pass

    try:
        # Top-5 models by all-time revenue
        models_r = (await db.execute(
            text(
                """
                SELECT COALESCE(m.name, t.model) AS name, SUM(t.amount) AS rev
                FROM transactions t
                LEFT JOIN models m ON m.id = t.model_id
                WHERE t.tenant_id = :tid AND t.type = 'income'
                GROUP BY 1 ORDER BY 2 DESC LIMIT 5
                """
            ),
            {"tid": tenant_id},
        )).fetchall()
        if models_r:
            parts = ", ".join(
                f"{r[0]} ${float(r[1]):,.0f}" for r in models_r if r[0]
            )
            auto_lines.append(f"Топ-5 моделей (всё время): {parts}")
    except Exception:
        pass

    try:
        # Avg RPC and Open Rate for last completed month via raw SQL
        today = date.today()
        lm = today.month - 1 if today.month > 1 else 12
        ly = today.year if today.month > 1 else today.year - 1

        kpi_r = (await db.execute(
            text(
                """
                SELECT
                    CASE WHEN SUM(kpi.chats) > 0
                         THEN SUM(kpi.revenue) / SUM(kpi.chats) ELSE NULL END AS avg_rpc,
                    CASE WHEN SUM(kpi.ppv_sent) > 0
                         THEN 100.0 * SUM(kpi.ppv_opened) / SUM(kpi.ppv_sent) ELSE NULL END AS avg_or
                FROM chatter_kpi kpi
                WHERE kpi.tenant_id = :tid
                  AND kpi.year = :yr AND kpi.month = :mo
                """
            ),
            {"tid": tenant_id, "yr": ly, "mo": lm},
        )).fetchone()

        if kpi_r:
            if kpi_r[0] is not None:
                auto_lines.append(f"Средний RPC (прошлый мес): ${float(kpi_r[0]):.2f}")
            if kpi_r[1] is not None:
                auto_lines.append(f"Средний Open Rate (прошлый мес): {float(kpi_r[1]):.1f}%")
    except Exception:
        pass

    # ── Manual thresholds ─────────────────────────────────────────────────────
    rpc_crit = float(profile.get("rpc_critical") or _DEFAULTS["rpc_critical"])
    rpc_low  = float(profile.get("rpc_working_low") or _DEFAULTS["rpc_working_low"])
    rpc_str  = float(profile.get("rpc_strong") or _DEFAULTS["rpc_strong"])
    or_crit  = float(profile.get("open_rate_critical") or _DEFAULTS["open_rate_critical"])
    or_low   = float(profile.get("open_rate_working") or _DEFAULTS["open_rate_working"])
    or_str   = float(profile.get("open_rate_strong") or _DEFAULTS["open_rate_strong"])

    # ── Assemble text ─────────────────────────────────────────────────────────
    sections: list[str] = ["=== ПАСПОРТ АГЕНТСТВА ==="]

    if auto_lines:
        sections.append("— Авто-данные: " + " | ".join(auto_lines))

    sections.append(
        f"— Пороги RPC: тревога <${rpc_crit:.2f} | рабочий ${rpc_crit:.2f}–${rpc_low:.2f} | "
        f"норма ${rpc_low:.2f}–${rpc_str:.2f} | отлично >${rpc_str:.2f}"
    )
    sections.append(
        f"— Пороги Open Rate: тревога <{or_crit:.0f}% | рабочий {or_crit:.0f}–{or_low:.0f}% | "
        f"норма {or_low:.0f}–{or_str:.0f}% | отлично >{or_str:.0f}%"
    )

    if profile.get("priorities"):
        sections.append(f"— Приоритеты владельца: {profile['priorities']}")
    if profile.get("glossary"):
        sections.append(f"— Глоссарий/заметки: {profile['glossary']}")
    if profile.get("target_notes"):
        sections.append(f"— Цели: {profile['target_notes']}")

    return "\n".join(sections)
