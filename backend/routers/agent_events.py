"""Agent events (memory layer) — CRUD endpoints for owner dashboard.

Routes are under /api/v1/agent-events to avoid collision with the existing
simple /api/v1/events (date-based finance events).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner, get_current_tenant
from models import AgentEvent, Tenant

logger = logging.getLogger("flowof.agent_events")
router = APIRouter(prefix="/api/v1/agent-events", tags=["agent-events"])

_OPEN_STATUSES    = ("proposed", "accepted", "in_progress", "review_due")
_ALL_STATUSES     = _OPEN_STATUSES + ("closed_success", "closed_failed", "dismissed")
_PRIORITY_ORDER   = {"high": 0, "normal": 1, "low": 2}


# ── Schemas ───────────────────────────────────────────────────────────────────

class AgentEventOut(BaseModel):
    id:                   int
    title:                str
    description:          str | None
    entity_type:          str | None
    entity_ref:           str | None
    trigger_metric:       str | None
    trigger_value_before: float | None
    status:               str
    source:               str
    created_by:           str
    priority:             str
    created_at:           datetime
    review_date:          date | None
    closed_at:            datetime | None
    outcome:              str | None
    outcome_value_after:  float | None
    related_chat_id:      str | None

    model_config = {"from_attributes": True}


class AgentEventCreate(BaseModel):
    title:                str
    description:          str | None = None
    entity_type:          str | None = None
    entity_ref:           str | None = None
    trigger_metric:       str | None = None
    trigger_value_before: float | None = None
    review_in_days:       int | None = None
    source:               str = "user"    # 'user' / 'chat' / 'watcher'
    priority:             str = "normal"


class AgentEventPatch(BaseModel):
    status:   str | None = None
    note:     str | None = None           # appended to description
    outcome:  str | None = None
    outcome_value_after: float | None = None
    review_date: date | None = None


def _to_out(ev: AgentEvent) -> AgentEventOut:
    return AgentEventOut(
        id=ev.id,
        title=ev.title,
        description=ev.description,
        entity_type=ev.entity_type,
        entity_ref=ev.entity_ref,
        trigger_metric=ev.trigger_metric,
        trigger_value_before=float(ev.trigger_value_before) if ev.trigger_value_before is not None else None,
        status=ev.status,
        source=ev.source,
        created_by=ev.created_by,
        priority=ev.priority,
        created_at=ev.created_at,
        review_date=ev.review_date,
        closed_at=ev.closed_at,
        outcome=ev.outcome,
        outcome_value_after=float(ev.outcome_value_after) if ev.outcome_value_after is not None else None,
        related_chat_id=ev.related_chat_id,
    )


# ── GET /agent-events ─────────────────────────────────────────────────────────

@router.get("", response_model=list[AgentEventOut])
async def list_agent_events(
    status: str | None = Query(None, description="Filter by status"),
    entity: str | None = Query(None, description="Filter by entity_ref (partial match)"),
    include_closed: bool = Query(False),
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    params: dict[str, Any] = {"tid": tenant.id}
    filters = ["ae.tenant_id = :tid"]

    if status:
        filters.append("ae.status = :status")
        params["status"] = status
    elif not include_closed:
        filters.append("ae.status NOT IN ('closed_success','closed_failed','dismissed')")

    if entity:
        filters.append("LOWER(ae.entity_ref) LIKE LOWER(:entity)")
        params["entity"] = f"%{entity}%"

    where = " AND ".join(filters)
    rows = (await db.execute(
        text(
            f"""
            SELECT ae.* FROM agent_events ae
            WHERE {where}
            ORDER BY
                CASE ae.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                ae.created_at DESC
            LIMIT 200
            """
        ),
        params,
    )).mappings().all()

    result = []
    for r in rows:
        result.append(AgentEventOut(
            id=r["id"],
            title=r["title"],
            description=r.get("description"),
            entity_type=r.get("entity_type"),
            entity_ref=r.get("entity_ref"),
            trigger_metric=r.get("trigger_metric"),
            trigger_value_before=float(r["trigger_value_before"]) if r.get("trigger_value_before") is not None else None,
            status=r["status"],
            source=r["source"],
            created_by=r["created_by"],
            priority=r["priority"],
            created_at=r["created_at"],
            review_date=r.get("review_date"),
            closed_at=r.get("closed_at"),
            outcome=r.get("outcome"),
            outcome_value_after=float(r["outcome_value_after"]) if r.get("outcome_value_after") is not None else None,
            related_chat_id=r.get("related_chat_id"),
        ))
    return result


# ── POST /agent-events ────────────────────────────────────────────────────────

@router.post("", response_model=AgentEventOut, status_code=201)
async def create_agent_event(
    body: AgentEventCreate,
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create an event — typically triggered by owner clicking 'Accept' on a proposed_event
    from the chat response, or manually from the events tab."""
    status = "proposed" if body.source == "chat" else "accepted"
    review_date = None
    if body.review_in_days:
        review_date = date.today() + timedelta(days=body.review_in_days)

    ev = AgentEvent(
        tenant_id=tenant.id,
        title=body.title.strip(),
        description=(body.description or "").strip() or None,
        entity_type=body.entity_type,
        entity_ref=body.entity_ref,
        trigger_metric=body.trigger_metric,
        trigger_value_before=body.trigger_value_before,
        status=status,
        source=body.source,
        created_by="owner",
        priority=body.priority,
        review_date=review_date,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    logger.info("created agent_event id=%s tenant=%s title=%r", ev.id, tenant.id, ev.title[:60])
    return _to_out(ev)


# ── PATCH /agent-events/{id} ──────────────────────────────────────────────────

@router.patch("/{event_id}", response_model=AgentEventOut)
async def patch_agent_event(
    event_id: int,
    body: AgentEventPatch,
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update status, append a note, or close with outcome."""
    result = await db.execute(
        text("SELECT * FROM agent_events WHERE id=:id AND tenant_id=:tid"),
        {"id": event_id, "tid": tenant.id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")

    updates: dict[str, Any] = {}

    if body.status is not None:
        if body.status not in _ALL_STATUSES:
            raise HTTPException(400, f"Неверный статус. Допустимые: {', '.join(_ALL_STATUSES)}")
        updates["status"] = body.status
        if body.status in ("closed_success", "closed_failed"):
            updates["closed_at"] = datetime.utcnow()

    if body.review_date is not None:
        updates["review_date"] = body.review_date

    if body.outcome is not None:
        updates["outcome"] = body.outcome.strip()
    if body.outcome_value_after is not None:
        updates["outcome_value_after"] = body.outcome_value_after

    if body.note:
        existing_desc = row.get("description") or ""
        updates["description"] = (
            existing_desc + f"\n[{datetime.utcnow().strftime('%d.%m.%Y %H:%M')}] {body.note.strip()}"
        ).strip()

    if updates:
        set_clause = ", ".join(f"{k}=:{k}" for k in updates)
        updates["id"] = event_id
        updates["tid"] = tenant.id
        await db.execute(
            text(f"UPDATE agent_events SET {set_clause} WHERE id=:id AND tenant_id=:tid"),
            updates,
        )
        await db.commit()

    refreshed = (await db.execute(
        text("SELECT * FROM agent_events WHERE id=:id AND tenant_id=:tid"),
        {"id": event_id, "tid": tenant.id},
    )).mappings().one()

    return AgentEventOut(
        id=refreshed["id"],
        title=refreshed["title"],
        description=refreshed.get("description"),
        entity_type=refreshed.get("entity_type"),
        entity_ref=refreshed.get("entity_ref"),
        trigger_metric=refreshed.get("trigger_metric"),
        trigger_value_before=float(refreshed["trigger_value_before"]) if refreshed.get("trigger_value_before") is not None else None,
        status=refreshed["status"],
        source=refreshed["source"],
        created_by=refreshed["created_by"],
        priority=refreshed["priority"],
        created_at=refreshed["created_at"],
        review_date=refreshed.get("review_date"),
        closed_at=refreshed.get("closed_at"),
        outcome=refreshed.get("outcome"),
        outcome_value_after=float(refreshed["outcome_value_after"]) if refreshed.get("outcome_value_after") is not None else None,
        related_chat_id=refreshed.get("related_chat_id"),
    )


# ── GET /agent-events/insights ────────────────────────────────────────────────

@router.post("/scan-now")
async def trigger_watcher_scan(
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Immediately run a watcher scan for the current tenant (manual trigger).
    Returns how many events were created at each level.
    """
    try:
        from services.agent_watcher import watcher_scan
        result = await watcher_scan(db, tenant.id)
        logger.info(
            "manual scan-now tenant=%s level_a=%s level_b=%s total=%s errors=%s",
            tenant.id, result.get("level_a"), result.get("level_b"),
            result.get("total"), result.get("errors"),
        )
        return result
    except BaseException as exc:
        # Should never reach here — watcher_scan is designed to never raise.
        # This final net ensures we always return 200 so the frontend can show the error.
        err_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("scan-now endpoint unhandled exception tenant=%s: %s", tenant.id, err_msg)
        try:
            await db.rollback()
        except Exception:
            pass
        return JSONResponse(
            status_code=200,
            content={"level_a": 0, "level_b": 0, "total": 0, "errors": [err_msg]},
        )


@router.post("/review-now")
async def trigger_watcher_review(
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Immediately run event review for all overdue events (manual trigger).
    Returns how many events were checked and updated.
    """
    from services.agent_watcher import watcher_review
    result = await watcher_review(db, tenant.id)
    logger.info(
        "manual review-now tenant=%s checked=%s updated=%s",
        tenant.id, result.get("checked"), result.get("updated"),
    )
    return result


@router.post("/dismiss-watcher")
async def dismiss_watcher_events(
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-dismiss all open watcher-sourced events for the current tenant.

    Sets status='dismissed' on every event where source='watcher' and
    status is in the open set. Returns {"dismissed": N}.
    """
    result = await db.execute(
        text(
            """
            UPDATE agent_events
               SET status = 'dismissed'
             WHERE tenant_id = :tid
               AND source    = 'watcher'
               AND status   IN ('proposed','accepted','in_progress','review_due')
            RETURNING id
            """
        ),
        {"tid": tenant.id},
    )
    dismissed = len(result.fetchall())
    await db.commit()
    logger.info("bulk dismiss-watcher tenant=%s dismissed=%s", tenant.id, dismissed)
    return {"dismissed": dismissed}


@router.get("/insights", response_model=list[AgentEventOut])
async def get_agent_insights(
    limit: int = Query(3, ge=1, le=10),
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Top-N highest-priority open events for the dashboard overview block."""
    rows = (await db.execute(
        text(
            """
            SELECT * FROM agent_events
            WHERE tenant_id = :tid
              AND status NOT IN ('closed_success','closed_failed','dismissed')
            ORDER BY
                CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT :lim
            """
        ),
        {"tid": tenant.id, "lim": limit},
    )).mappings().all()

    return [
        AgentEventOut(
            id=r["id"],
            title=r["title"],
            description=r.get("description"),
            entity_type=r.get("entity_type"),
            entity_ref=r.get("entity_ref"),
            trigger_metric=r.get("trigger_metric"),
            trigger_value_before=float(r["trigger_value_before"]) if r.get("trigger_value_before") is not None else None,
            status=r["status"],
            source=r["source"],
            created_by=r["created_by"],
            priority=r["priority"],
            created_at=r["created_at"],
            review_date=r.get("review_date"),
            closed_at=r.get("closed_at"),
            outcome=r.get("outcome"),
            outcome_value_after=float(r["outcome_value_after"]) if r.get("outcome_value_after") is not None else None,
            related_chat_id=r.get("related_chat_id"),
        )
        for r in rows
    ]
