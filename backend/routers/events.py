import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Event
from schemas import EventCreate, EventOut

logger = logging.getLogger("flowof.events")
router = APIRouter(prefix="/api/v1", tags=["events"])


@router.get("/events", response_model=list[EventOut])
async def list_events(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event)
        .where(Event.tenant_id == tenant.id)
        .order_by(Event.date.desc())
    )
    return result.scalars().all()


@router.post("/events", response_model=EventOut, status_code=201)
async def create_event(
    body: EventCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    event = Event(
        tenant_id=tenant.id,
        date=body.date,
        description=body.description.strip(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    logger.info("Created event id=%d tenant=%d", event.id, tenant.id)
    return event


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(
            and_(Event.id == event_id, Event.tenant_id == tenant.id)
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.delete(event)
    await db.commit()
