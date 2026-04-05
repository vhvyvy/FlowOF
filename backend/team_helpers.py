"""Team scoping for transactions and default team bootstrap."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Team, Transaction


async def list_teams(db: AsyncSession, tenant_id: int) -> list[Team]:
    r = await db.execute(
        select(Team)
        .where(Team.tenant_id == tenant_id)
        .order_by(Team.sort_order, Team.id)
    )
    return list(r.scalars().all())


async def ensure_default_team(db: AsyncSession, tenant_id: int) -> Team:
    teams = await list_teams(db, tenant_id)
    if teams:
        return teams[0]
    t = Team(
        tenant_id=tenant_id,
        name="Основная команда",
        sort_order=0,
        inherit_economics=True,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


def team_transaction_clause(team_id: int | None, default_team_id: int | None):
    """
    None → no extra clause (all teams).
    Otherwise: default team includes legacy rows with team_id IS NULL.
    """
    if team_id is None:
        return None
    if default_team_id is not None and team_id == default_team_id:
        return or_(Transaction.team_id == team_id, Transaction.team_id.is_(None))
    return Transaction.team_id == team_id


def normalize_notion_db_id(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().replace("-", "")
    if len(s) == 32:
        return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    return raw.strip()
