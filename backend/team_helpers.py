"""Team scoping for transactions and default team bootstrap."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Team, Transaction

# Ищем ровно 32 hex-символа, окружённые не-hex (или на границе строки)
_HEX32_BOUNDARY = re.compile(r'(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])')


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


def team_inherits_global_economics(team) -> bool:
    """NULL / missing → inherit global settings (как основная команда)."""
    v = getattr(team, "inherit_economics", None)
    return True if v is None else bool(v)


def normalize_notion_db_id(raw: str | None) -> str | None:
    """
    Принимает любой формат:
    - голый 32-символьный hex: 317fad2b5c57804a84efce5a775c8224
    - UUID с дефисами:         317fad2b-5c57-804a-84ef-ce5a775c8224
    - полная ссылка Notion:    https://www.notion.so/317fad2b5c57804a84efce5a775c8224?v=…
    - ссылка с названием:      https://www.notion.so/workspace/My-Title-317fad2b5c57804a84efce5a775c8224

    Возвращает UUID-формат (8-4-4-4-12) или None.
    """
    if not raw:
        return None
    s = raw.strip()

    def _format(h: str) -> str:
        h = h.lower()
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

    def _extract_from_segment(segment: str) -> str | None:
        """ID всегда стоит последним в сегменте пути (после названия через '-').
        Убираем дефисы и берём последние 32 символа — если все hex, это ID."""
        seg_no_dash = segment.replace("-", "")
        if len(seg_no_dash) >= 32:
            tail = seg_no_dash[-32:]
            if re.fullmatch(r'[0-9a-fA-F]{32}', tail):
                return _format(tail)
        return None

    # Если это URL — берём последний непустой сегмент пути (до '?' и '#')
    if s.startswith("http://") or s.startswith("https://"):
        try:
            parsed = urlparse(s)
            segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            result = _extract_from_segment(segment)
            if result:
                return result
        except Exception:
            pass

    # Голый UUID с дефисами или без: убираем дефисы, проверяем на 32 hex
    no_dash = s.replace("-", "")
    if re.fullmatch(r'[0-9a-fA-F]{32}', no_dash):
        return _format(no_dash)

    # Крайний случай: ищем первый ровно-32-символьный hex-блок на границах
    m = _HEX32_BOUNDARY.search(no_dash)
    if m:
        return _format(m.group(1))
    return None
