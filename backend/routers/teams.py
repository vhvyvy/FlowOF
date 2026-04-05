import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Team
from schemas import TeamOut, TeamCreate, TeamUpdate
from team_helpers import list_teams, ensure_default_team, normalize_notion_db_id

logger = logging.getLogger("skynet.teams")
router = APIRouter(prefix="/api/v1", tags=["teams"])


def _to_out(t: Team) -> TeamOut:
    return TeamOut(
        id=t.id,
        name=t.name,
        sort_order=t.sort_order or 0,
        notion_database_id=t.notion_database_id,
        inherit_economics=bool(t.inherit_economics),
        chatter_max_pct=float(t.chatter_max_pct) if t.chatter_max_pct is not None else None,
        default_chatter_pct=float(t.default_chatter_pct) if t.default_chatter_pct is not None else None,
        admin_percent_total=float(t.admin_percent_total) if t.admin_percent_total is not None else None,
    )


@router.get("/teams", response_model=list[TeamOut])
async def get_teams(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    await ensure_default_team(db, tenant.id)
    teams = await list_teams(db, tenant.id)
    return [_to_out(t) for t in teams]


@router.post("/teams", response_model=TeamOut, status_code=201)
async def create_team(
    body: TeamCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    await ensure_default_team(db, tenant.id)
    t = Team(
        tenant_id=tenant.id,
        name=body.name.strip(),
        sort_order=body.sort_order,
        notion_database_id=normalize_notion_db_id(body.notion_database_id),
        inherit_economics=body.inherit_economics,
        chatter_max_pct=body.chatter_max_pct,
        default_chatter_pct=body.default_chatter_pct,
        admin_percent_total=body.admin_percent_total,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    logger.info("team created id=%d tenant=%d", t.id, tenant.id)
    return _to_out(t)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: int,
    body: TeamUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Team).where(and_(Team.id == team_id, Team.tenant_id == tenant.id))
    )
    t = r.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    if body.name is not None:
        t.name = body.name.strip()
    if body.sort_order is not None:
        t.sort_order = body.sort_order
    if body.notion_database_id is not None:
        t.notion_database_id = normalize_notion_db_id(body.notion_database_id)
    if body.inherit_economics is not None:
        t.inherit_economics = body.inherit_economics
    if body.chatter_max_pct is not None:
        t.chatter_max_pct = body.chatter_max_pct
    if body.default_chatter_pct is not None:
        t.default_chatter_pct = body.default_chatter_pct
    if body.admin_percent_total is not None:
        t.admin_percent_total = body.admin_percent_total
    await db.commit()
    await db.refresh(t)
    return _to_out(t)
