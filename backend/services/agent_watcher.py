"""Agent Watcher — proactive anomaly scanner and event reviewer.

Two capabilities:
  watcher_scan(db, tenant_id)    — finds problems, creates accepted events
  watcher_review(db, tenant_id)  — checks events past their review_date

Anti-spam invariants:
  - Per (tenant_id, entity_type, entity_ref): skip if open event already exists.
  - Per dismissed entity: silent for 14 days after dismissal.
  - Level-A fires only on hard threshold breaches (not soft warnings).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.agent_watcher")

# ── Name normalisation (mirrors analyst_tools._norm_chatter_name) ─────────────

def _norm_ref(ref: str | None) -> str:
    """Canonical entity_ref: strip whitespace + leading '@', lowercase."""
    if not ref:
        return ""
    return ref.strip().lstrip("@").strip().lower()

# SQL expression that applies the same normalisation to a stored column.
_SQL_NORM = "LOWER(TRIM(LEADING '@' FROM TRIM(COALESCE({col},''))))"

# ── Anti-spam helpers ─────────────────────────────────────────────────────────

# All non-final statuses — an event in any of these means the entity is
# already being tracked.
_OPEN_STATUSES_TUPLE = "('proposed','accepted','in_progress','review_due')"


async def _has_open_event(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str | None,
    entity_ref: str | None,
) -> bool:
    """Return True if there is already an open event for this entity.

    'Open' = any non-final status: proposed, accepted, in_progress, review_due.
    entity_ref is normalised: '@Vyach3slav' and 'Vyach3slav' are the same.
    """
    if not entity_ref:
        return False
    norm = _norm_ref(entity_ref)
    row = (await db.execute(
        text(
            f"""
            SELECT 1 FROM agent_events
            WHERE tenant_id = :tid
              AND LOWER(COALESCE(entity_type,'')) = LOWER(COALESCE(:etype,''))
              AND {_SQL_NORM.format(col='entity_ref')} = :norm
              AND status IN {_OPEN_STATUSES_TUPLE}
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "etype": entity_type or "", "norm": norm},
    )).fetchone()
    return row is not None


async def _recently_dismissed(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str | None,
    entity_ref: str | None,
    days: int = 14,
) -> bool:
    """Return True if this entity was dismissed within the last `days` days."""
    if not entity_ref:
        return False
    norm = _norm_ref(entity_ref)
    cutoff = datetime.utcnow() - timedelta(days=days)
    row = (await db.execute(
        text(
            f"""
            SELECT 1 FROM agent_events
            WHERE tenant_id = :tid
              AND LOWER(COALESCE(entity_type,'')) = LOWER(COALESCE(:etype,''))
              AND {_SQL_NORM.format(col='entity_ref')} = :norm
              AND status = 'dismissed'
              AND closed_at >= :cutoff
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "etype": entity_type or "", "norm": norm, "cutoff": cutoff},
    )).fetchone()
    return row is not None


async def _safe_create_event(
    db: AsyncSession,
    tenant_id: int,
    *,
    title: str,
    description: str,
    entity_type: str | None,
    entity_ref: str | None,
    trigger_metric: str | None,
    trigger_value_before: float | None,
    priority: str,
    review_in_days: int,
) -> bool:
    """Create a watcher event after anti-spam checks. Returns True if created."""
    if await _has_open_event(db, tenant_id, entity_type, entity_ref):
        logger.debug("watcher skip duplicate: entity=%s/%s", entity_type, entity_ref)
        return False
    if await _recently_dismissed(db, tenant_id, entity_type, entity_ref):
        logger.debug("watcher skip recently dismissed: entity=%s/%s", entity_type, entity_ref)
        return False

    review_date = date.today() + timedelta(days=review_in_days)
    await db.execute(
        text(
            """
            INSERT INTO agent_events
              (tenant_id, title, description, entity_type, entity_ref,
               trigger_metric, trigger_value_before, status, source,
               created_by, priority, created_at, review_date)
            VALUES
              (:tid, :title, :desc, :etype, :eref,
               :metric, :val, 'accepted', 'watcher',
               'agent', :prio, NOW(), :rdate)
            """
        ),
        {
            "tid":   tenant_id,
            "title": title[:255],
            "desc":  description[:2000],
            "etype": entity_type,
            "eref":  entity_ref,
            "metric":trigger_metric,
            "val":   trigger_value_before,
            "prio":  priority,
            "rdate": review_date,
        },
    )
    await db.commit()
    logger.info(
        "watcher created event: tenant=%s entity=%s/%s metric=%s val=%s",
        tenant_id, entity_type, entity_ref, trigger_metric, trigger_value_before,
    )
    return True


# ── Last completed month helper ───────────────────────────────────────────────

def _last_completed_month() -> tuple[int, int]:
    today = date.today()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


# ── LEVEL A — threshold rules (no LLM) ───────────────────────────────────────

async def _level_a_scan(
    db: AsyncSession,
    tenant_id: int,
    profile: dict[str, Any],
) -> int:
    """Detect hard threshold breaches using find_anomalies + agency_profile thresholds."""
    from services.analyst_tools import find_anomalies

    year, month = _last_completed_month()
    rpc_critical = float(profile.get("rpc_critical") or 0.15)
    or_critical  = float(profile.get("open_rate_critical") or 20.0)

    try:
        anomalies = await find_anomalies(db, tenant_id, year=year, month=month)
    except Exception as exc:
        logger.warning("watcher level_a find_anomalies error tenant=%s: %s", tenant_id, exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0

    created = 0
    for a in anomalies:
        atype = a.get("type", "")

        if atype == "revenue_drop":
            chatter = a.get("chatter", "")
            pct     = abs(float(a.get("drop_pct", 0)))
            if pct < 40:
                continue  # only hard breaches
            ok = await _safe_create_event(
                db, tenant_id,
                title=f"Падение выручки чаттера {chatter} на {pct:.0f}%",
                description=(
                    f"Выручка {chatter} упала на {pct:.0f}% по сравнению с прошлым месяцем. "
                    f"Текущий период: {year}-{month:02d}."
                ),
                entity_type="chatter",
                entity_ref=chatter,
                trigger_metric="revenue_mom_pct",
                trigger_value_before=float(a.get("prev_revenue", 0) or 0),
                priority="high",
                review_in_days=7,
            )
            if ok:
                created += 1

        elif atype == "low_rpc":
            chatter = a.get("chatter", "")
            rpc     = float(a.get("rpc", 0) or 0)
            if rpc >= rpc_critical:
                continue  # not below critical threshold
            ok = await _safe_create_event(
                db, tenant_id,
                title=f"Низкий RPC чаттера {chatter}: ${rpc:.2f}",
                description=(
                    f"RPC {chatter} = ${rpc:.2f} — ниже критического порога ${rpc_critical:.2f}. "
                    f"Период: {year}-{month:02d}."
                ),
                entity_type="chatter",
                entity_ref=chatter,
                trigger_metric="rpc",
                trigger_value_before=rpc,
                priority="high" if rpc < rpc_critical * 0.5 else "normal",
                review_in_days=14,
            )
            if ok:
                created += 1

        elif atype == "concentration_risk":
            top_pct = float(a.get("top3_pct", 0) or 0)
            if top_pct < 80:
                continue
            ok = await _safe_create_event(
                db, tenant_id,
                title=f"Риск концентрации: топ-3 модели = {top_pct:.0f}% выручки",
                description=(
                    f"Топ-3 модели дают {top_pct:.0f}% всей выручки агентства. "
                    f"Период: {year}-{month:02d}. Диверсифицировать источники дохода."
                ),
                entity_type="agency",
                entity_ref="concentration_risk",
                trigger_metric="top3_revenue_pct",
                trigger_value_before=top_pct,
                priority="normal",
                review_in_days=30,
            )
            if ok:
                created += 1

    # ── Low Open Rate check (direct KPI query, not in find_anomalies) ─────────
    try:
        from services.analyst_tools import get_chatter_kpi_tool
        kpi_rows = await get_chatter_kpi_tool(db, tenant_id, year=year, month=month)
        for row in kpi_rows:
            orate = row.get("ppv_open_rate")
            if orate is None:
                continue
            orate = float(orate)
            if orate >= or_critical:
                continue
            chatter = row.get("chatter", "")
            ok = await _safe_create_event(
                db, tenant_id,
                title=f"Низкий Open Rate {chatter}: {orate:.1f}%",
                description=(
                    f"Open Rate {chatter} = {orate:.1f}% — ниже критического порога "
                    f"{or_critical:.0f}%. Период: {year}-{month:02d}."
                ),
                entity_type="chatter",
                entity_ref=chatter,
                trigger_metric="open_rate",
                trigger_value_before=orate,
                priority="high" if orate < or_critical * 0.7 else "normal",
                review_in_days=14,
            )
            if ok:
                created += 1
    except Exception as exc:
        logger.warning("watcher level_a kpi error tenant=%s: %s", tenant_id, exc)
        try:
            await db.rollback()
        except Exception:
            pass

    return created


# Read-only tool names safe for the watcher B-scan.
# Write tools (create_event, update_event_status, close_event) are
# intentionally excluded — the LLM must not call them during a scan;
# it should only return a JSON list of findings.
_WATCHER_READ_TOOL_NAMES = frozenset({
    "get_agency_summary",
    "get_monthly_trend",
    "get_top_chatters",
    "get_chatter_detail",
    "get_chatter_kpi_tool",
    "get_model_performance",
    "get_shift_breakdown",
    "query_transactions_flexible",
    "find_anomalies",
    "get_open_events",
})


def _extract_json_array(text: str) -> list | None:
    """Robustly extract a JSON array from LLM output.

    Handles:
      - Plain JSON array
      - Wrapped in ```json ... ``` fences
      - Array embedded in prose text
    """
    # 1. Try to parse the full text first
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # 2. Strip markdown fences (``` or ```json)
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # 3. Find first [...] block in the text (handles prose around it)
    array_match = re.search(r"\[.*?\]", stripped, re.DOTALL)
    if array_match:
        try:
            parsed = json.loads(array_match.group())
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    return None


# ── LEVEL B — LLM trend detection ─────────────────────────────────────────────

async def _level_b_scan(db: AsyncSession, tenant_id: int) -> tuple[int, str | None]:
    """Ask the LLM to find subtle 2-3 month sliding trends not caught by rules.

    Returns (created_count, error_str | None).
    Never raises — all exceptions are caught and returned as error_str.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("watcher level_b: ANTHROPIC_API_KEY not set, skipping")
        return 0, None

    try:
        from anthropic import AsyncAnthropic
        from services.analyst_tools import TOOL_DESCRIPTIONS, TOOL_REGISTRY
        from services.agency_profile import build_profile_context
    except ImportError as exc:
        return 0, f"import error: {exc}"

    # Restrict to read-only tools — prevent LLM from accidentally writing events
    watcher_tools = [t for t in TOOL_DESCRIPTIONS if t["name"] in _WATCHER_READ_TOOL_NAMES]

    profile_ctx = ""
    try:
        profile_ctx = await build_profile_context(db, tenant_id)
    except Exception as exc:
        logger.debug("watcher level_b: profile context failed: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass

    analyst_model = os.getenv("AI_ANALYST_MODEL", "claude-sonnet-4-6")
    client = AsyncAnthropic(api_key=api_key)

    system = (
        "Ты проактивный аналитик OnlyFans-агентства. Твоя задача — обнаружить "
        "ПОЛЗУЩИЕ риски: метрики, которые ухудшаются 2-3 месяца подряд, ещё не "
        "пробив критический порог, но уже в зоне риска.\n"
        "Вызывай инструменты (только для чтения). Ищи сползание RPC, Open Rate, "
        "выручки по чаттерам за последние 3 месяца.\n"
        "В ФИНАЛЬНОМ ОТВЕТЕ верни ТОЛЬКО JSON-массив (без пояснений, без markdown):\n"
        '[{"title":"...","description":"...","entity_type":"chatter|model|agency",'
        '"entity_ref":"имя или null","trigger_metric":"...","trigger_value":число,'
        '"priority":"high|normal|low","review_in_days":число}]\n'
        "Если трендов нет — верни [].\n"
        "НЕ вызывай create_event или другие write-инструменты — только read."
    )
    if profile_ctx:
        system = profile_ctx + "\n\n" + system

    question = (
        "Проведи полный осмотр агентства за последние 3 месяца. "
        "Найди все сползающие тренды и скрытые риски. "
        "В ответе верни ТОЛЬКО JSON-массив findings."
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    iterations = 0
    max_iter   = 6
    findings: list[dict] = []
    raw_final  = ""

    try:
        while iterations < max_iter:
            iterations += 1
            try:
                resp = await client.messages.create(
                    model=analyst_model,
                    max_tokens=2000,
                    system=system,
                    tools=watcher_tools,  # type: ignore[arg-type]
                    messages=messages,
                )
            except Exception as exc:
                logger.warning("watcher level_b LLM call error tenant=%s: %s", tenant_id, exc)
                return 0, f"LLM call failed: {exc}"

            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                # Extract JSON from final response
                for block in resp.content:
                    if hasattr(block, "text"):
                        raw_final = block.text
                        parsed = _extract_json_array(raw_final)
                        if parsed is not None:
                            findings = parsed
                        else:
                            logger.warning(
                                "watcher level_b: could not parse JSON from response "
                                "tenant=%s raw=%r", tenant_id, raw_final[:300]
                            )
                        break
                break

            # Handle tool calls (read-only tools only)
            tool_results: list[dict[str, Any]] = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                fn = TOOL_REGISTRY.get(block.name)
                if fn is None or block.name not in _WATCHER_READ_TOOL_NAMES:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"error": f"tool '{block.name}' not available in watcher"}),
                        "is_error": True,
                    })
                    continue
                try:
                    result = await fn(db, tenant_id, **(block.input or {}))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                except Exception as exc:
                    logger.warning("watcher level_b tool=%s error: %s", block.name, exc)
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"error": str(exc)}),
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

    except Exception as exc:
        logger.exception("watcher level_b unexpected error tenant=%s: %s", tenant_id, exc)
        return 0, str(exc)

    # Create events for each finding
    created = 0
    for f in findings:
        try:
            ok = await _safe_create_event(
                db, tenant_id,
                title=str(f.get("title", "Тренд"))[:255],
                description=str(f.get("description", ""))[:2000],
                entity_type=f.get("entity_type"),
                entity_ref=f.get("entity_ref"),
                trigger_metric=f.get("trigger_metric"),
                trigger_value_before=(
                    float(f["trigger_value"])
                    if f.get("trigger_value") is not None else None
                ),
                priority=f.get("priority", "normal"),
                review_in_days=int(f.get("review_in_days") or 14),
            )
            if ok:
                created += 1
        except Exception as exc:
            logger.warning("watcher level_b create event error: %s", exc)

    return created, None


# ── PUBLIC: watcher_scan ───────────────────────────────────────────────────────

async def watcher_scan(db: AsyncSession, tenant_id: int) -> dict:
    """Run full proactive scan: Level A (rules) + Level B (LLM trends).

    Returns:
        {
            "level_a": N,   # events created by threshold rules
            "level_b": M,   # events created by LLM trend detection
            "total": N+M,
            "errors": []    # list of error strings from failed sub-steps
        }

    Never raises — partial failures are captured in the "errors" list so the
    caller can always return a structured response.
    """
    logger.info("watcher_scan START tenant=%s", tenant_id)

    errors: list[str] = []
    a = 0
    b = 0

    # Load agency profile (used by Level A thresholds)
    profile: dict = {}
    try:
        from services.agency_profile import get_agency_profile
        profile = await get_agency_profile(db, tenant_id)
    except Exception as exc:
        err = f"profile load failed: {exc}"
        logger.warning("watcher_scan %s tenant=%s", err, tenant_id)
        errors.append(err)
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Level A: threshold rules ───────────────────────────────────────────────
    try:
        a = await _level_a_scan(db, tenant_id, profile)
    except Exception as exc:
        err = f"level_a crashed: {exc}"
        logger.exception("watcher_scan %s tenant=%s", err, tenant_id)
        errors.append(err)
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Level B: LLM trend detection ──────────────────────────────────────────
    try:
        b, b_err = await _level_b_scan(db, tenant_id)
        if b_err:
            errors.append(f"level_b: {b_err}")
    except Exception as exc:
        err = f"level_b crashed: {exc}"
        logger.exception("watcher_scan %s tenant=%s", err, tenant_id)
        errors.append(err)
        try:
            await db.rollback()
        except Exception:
            pass

    total = a + b
    logger.info(
        "watcher_scan DONE tenant=%s level_a=%s level_b=%s total=%s errors=%s",
        tenant_id, a, b, total, errors,
    )
    return {"level_a": a, "level_b": b, "total": total, "errors": errors}


# ── PUBLIC: watcher_review ─────────────────────────────────────────────────────

async def watcher_review(db: AsyncSession, tenant_id: int) -> dict[str, int]:
    """Check events whose review_date has passed. Fetch current metric values,
    compare with trigger_value_before, update outcome.

    Returns {"checked": N, "updated": M}
    """
    logger.info("watcher_review START tenant=%s", tenant_id)
    today = date.today()

    rows = (await db.execute(
        text(
            """
            SELECT id, entity_type, entity_ref, trigger_metric, trigger_value_before, title
            FROM agent_events
            WHERE tenant_id   = :tid
              AND review_date <= :today
              AND status IN ('accepted', 'in_progress')
            ORDER BY review_date ASC
            LIMIT 50
            """
        ),
        {"tid": tenant_id, "today": today},
    )).mappings().all()

    checked = 0
    updated = 0

    for ev in rows:
        checked += 1
        ev_id       = ev["id"]
        entity_type = ev["entity_type"] or ""
        entity_ref  = ev["entity_ref"]  or ""
        metric      = ev["trigger_metric"] or ""
        val_before  = float(ev["trigger_value_before"]) if ev["trigger_value_before"] is not None else None

        current_val: float | None = None
        try:
            current_val = await _fetch_current_metric(
                db, tenant_id, entity_type, entity_ref, metric
            )
        except Exception as exc:
            logger.warning("watcher_review fetch metric error id=%s: %s", ev_id, exc)
            try:
                await db.rollback()
            except Exception:
                pass

        # Compose outcome text
        outcome = _build_outcome_text(metric, val_before, current_val)
        new_status = _determine_status(metric, val_before, current_val)

        try:
            await db.execute(
                text(
                    """
                    UPDATE agent_events
                    SET status             = :status,
                        outcome            = :outcome,
                        outcome_value_after= :oval,
                        closed_at          = CASE WHEN :status IN ('closed_success','closed_failed')
                                              THEN NOW() ELSE closed_at END
                    WHERE id = :eid AND tenant_id = :tid
                    """
                ),
                {
                    "status":  new_status,
                    "outcome": outcome,
                    "oval":    current_val,
                    "eid":     ev_id,
                    "tid":     tenant_id,
                },
            )
            await db.commit()
            updated += 1
            logger.info(
                "watcher_review updated id=%s status=%s before=%s after=%s",
                ev_id, new_status, val_before, current_val,
            )
        except Exception as exc:
            logger.warning("watcher_review update error id=%s: %s", ev_id, exc)
            try:
                await db.rollback()
            except Exception:
                pass

    logger.info(
        "watcher_review DONE tenant=%s checked=%s updated=%s",
        tenant_id, checked, updated,
    )
    return {"checked": checked, "updated": updated}


# ── Metric fetchers ───────────────────────────────────────────────────────────

async def _fetch_current_metric(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str,
    entity_ref: str,
    metric: str,
) -> float | None:
    """Fetch the latest value of `metric` for a given entity."""
    year, month = _last_completed_month()

    if entity_type == "chatter" and entity_ref:
        if metric == "rpc":
            from services.analyst_tools import get_chatter_kpi_tool
            rows = await get_chatter_kpi_tool(db, tenant_id, year=year, month=month)
            from services.analyst_tools import _norm_chatter_name
            norm = _norm_chatter_name(entity_ref)
            for r in rows:
                if _norm_chatter_name(r.get("chatter", "")) == norm:
                    v = r.get("rpc")
                    return float(v) if v is not None else None
        elif metric == "open_rate":
            from services.analyst_tools import get_chatter_kpi_tool
            rows = await get_chatter_kpi_tool(db, tenant_id, year=year, month=month)
            from services.analyst_tools import _norm_chatter_name
            norm = _norm_chatter_name(entity_ref)
            for r in rows:
                if _norm_chatter_name(r.get("chatter", "")) == norm:
                    v = r.get("ppv_open_rate")
                    return float(v) if v is not None else None
        elif metric in ("revenue", "revenue_mom_pct"):
            from services.analyst_tools import get_chatter_detail
            detail = await get_chatter_detail(
                db, tenant_id, chatter_name=entity_ref, months_back=1
            )
            h = detail.get("history", [])
            if h:
                return float(h[0].get("revenue", 0))

    if entity_type == "agency" and entity_ref == "concentration_risk":
        from services.analyst_tools import find_anomalies
        anomalies = await find_anomalies(db, tenant_id, year=year, month=month)
        for a in anomalies:
            if a.get("type") == "concentration_risk":
                return float(a.get("top3_pct", 0) or 0)

    return None


def _build_outcome_text(
    metric: str,
    before: float | None,
    after: float | None,
) -> str:
    if before is None and after is None:
        return "Не удалось получить актуальные данные для оценки."
    if after is None:
        return "Актуальные данные по метрике недоступны."
    if before is None:
        return f"Текущее значение {metric}: {after:.2f}."

    diff = after - before
    sign = "+" if diff >= 0 else ""
    prefix = {
        "rpc":             f"RPC: ${before:.2f} → ${after:.2f} ({sign}{diff:.2f})",
        "open_rate":       f"Open Rate: {before:.1f}% → {after:.1f}% ({sign}{diff:.1f}%)",
        "revenue_mom_pct": f"Выручка: {before:.0f} → {after:.0f} ({sign}{diff:.0f})",
        "revenue":         f"Выручка: ${before:.0f} → ${after:.0f}",
        "top3_revenue_pct":f"Концентрация топ-3: {before:.0f}% → {after:.0f}%",
    }.get(metric, f"{metric}: {before} → {after}")

    if diff > 0:
        return prefix + " — улучшилось"
    if diff < 0:
        return prefix + " — ухудшилось"
    return prefix + " — без изменений"


def _determine_status(
    metric: str,
    before: float | None,
    after: float | None,
) -> str:
    """Conservatively determine review outcome status.
    By default keep review_due to let the owner make the final call.
    Only auto-close if change is unambiguous and significant.
    """
    if before is None or after is None:
        return "review_due"

    diff = after - before
    # Metrics where higher is better
    higher_better = {"rpc", "open_rate", "revenue", "revenue_mom_pct"}
    # Metrics where lower is better
    lower_better  = {"top3_revenue_pct"}

    if metric in higher_better:
        if diff > 0 and abs(diff / max(abs(before), 0.001)) > 0.15:
            return "closed_success"
        if diff < 0 and abs(diff / max(abs(before), 0.001)) > 0.15:
            return "closed_failed"
    elif metric in lower_better:
        if diff < 0 and abs(diff / max(abs(before), 0.001)) > 0.10:
            return "closed_success"
        if diff > 0 and abs(diff / max(abs(before), 0.001)) > 0.10:
            return "closed_failed"

    # Conservative: leave for owner
    return "review_due"
