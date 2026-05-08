import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Team, Transaction
from schemas import TeamOut, TeamCreate, TeamUpdate
from team_helpers import (
    list_teams,
    ensure_default_team,
    normalize_team_notion_db_field,
    team_inherits_global_economics,
)
from team_bootstrap import assign_transactions_by_notion_database, backfill_notion_database_id_from_notion_api

logger = logging.getLogger("flowof.teams")
router = APIRouter(prefix="/api/v1", tags=["teams"])


def _to_out(t: Team) -> TeamOut:
    return TeamOut(
        id=t.id,
        name=t.name,
        sort_order=t.sort_order or 0,
        notion_database_id=t.notion_database_id,
        color_key=t.color_key,
        inherit_economics=team_inherits_global_economics(t),
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
        notion_database_id=normalize_team_notion_db_field(body.notion_database_id),
        color_key=(body.color_key or "").strip() or None,
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
        t.notion_database_id = normalize_team_notion_db_field(body.notion_database_id)
    if body.color_key is not None:
        t.color_key = body.color_key.strip() or None
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


@router.delete("/teams/{team_id}", status_code=204)
async def delete_team(
    team_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    teams = await list_teams(db, tenant.id)
    if not teams:
        raise HTTPException(status_code=404, detail="Команда не найдена")

    # Первая команда (основная) — нельзя удалять
    if teams[0].id == team_id:
        raise HTTPException(status_code=400, detail="Основную команду удалить нельзя")

    r = await db.execute(
        select(Team).where(and_(Team.id == team_id, Team.tenant_id == tenant.id))
    )
    t = r.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Команда не найдена")

    # Открепить транзакции этой команды (team_id → NULL)
    await db.execute(
        update(Transaction)
        .where(Transaction.tenant_id == tenant.id, Transaction.team_id == team_id)
        .values(team_id=None)
    )
    await db.delete(t)
    await db.commit()
    logger.info("team deleted id=%d tenant=%d", team_id, tenant.id)


class TeamReconcileOut(BaseModel):
    assigned_rows: int
    backfilled_pages: int


@router.post("/teams/reconcile-notion", response_model=TeamReconcileOut)
async def reconcile_notion_transactions(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    1) Подтянуть parent.database_id из Notion по notion_id страницы (нужен notion_token у тенанта).
    2) Проставить team_id по совпадению notion_database_id транзакции с командой.
    """
    tr = await db.execute(select(Tenant).where(Tenant.id == tenant.id))
    row = tr.scalar_one()
    backfilled = 0
    if row.notion_token and row.notion_token.strip():
        try:
            backfilled = await backfill_notion_database_id_from_notion_api(
                db, tenant.id, row.notion_token, limit=200
            )
        except Exception as e:
            logger.warning("notion backfill failed: %s", e)
    assigned = await assign_transactions_by_notion_database(db)
    return TeamReconcileOut(assigned_rows=assigned, backfilled_pages=backfilled)
