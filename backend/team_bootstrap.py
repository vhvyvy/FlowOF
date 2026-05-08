"""Create default + second team; assign transactions by Notion database id."""
from __future__ import annotations

import logging
import os

from sqlalchemy import text, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Team, Tenant, Transaction
from team_helpers import ensure_default_team, list_teams, normalize_notion_db_id

logger = logging.getLogger("flowof.team_bootstrap")

# Вторая команда — база Notion с транзакциями (можно переопределить env)
DEFAULT_TEAM2_NOTION_RAW = os.getenv(
    "NOTION_TEAM2_DATABASE_ID",
    "336fad2b5c578194a67dd4ddda4924c7",
)


async def bootstrap_teams(db: AsyncSession) -> None:
    """Ensure «Основная команда» + «Команда 2» с экономикой 22% / 8% админам."""
    canon = normalize_notion_db_id(DEFAULT_TEAM2_NOTION_RAW)
    if not canon:
        logger.warning("NOTION_TEAM2_DATABASE_ID is invalid, skip team 2 bootstrap")
    r = await db.execute(select(Tenant.id))
    tenant_ids = [row[0] for row in r.all()]

    for tid in tenant_ids:
        await ensure_default_team(db, tid)
        teams = await list_teams(db, tid)
        canon_set = {
            normalize_notion_db_id(t.notion_database_id)
            for t in teams
            if t.notion_database_id
        }
        if canon and canon in canon_set:
            continue
        if not canon:
            continue
        # Уже есть вторая команда по имени — дописываем notion id
        renamed = False
        for t in teams:
            if t.name.strip() in ("Команда 2", "Вторая команда") and not t.notion_database_id and canon:
                t.notion_database_id = canon
                if t.inherit_economics is not False:
                    t.inherit_economics = False
                if t.chatter_max_pct is None:
                    t.chatter_max_pct = 22
                if t.default_chatter_pct is None:
                    t.default_chatter_pct = 22
                if t.admin_percent_total is None:
                    t.admin_percent_total = 8
                renamed = True
        if renamed:
            continue
        if canon and canon not in canon_set:
            db.add(
                Team(
                    tenant_id=tid,
                    name="Команда 2",
                    sort_order=1,
                    notion_database_id=canon,
                    inherit_economics=False,
                    chatter_max_pct=22,
                    default_chatter_pct=22,
                    admin_percent_total=8,
                )
            )
    await db.commit()


async def assign_transactions_by_notion_database(db: AsyncSession) -> int:
    """
    Проставить team_id там, где notion_database_id транзакции присутствует в списке
    notion_database_id команды (поле может содержать несколько ID через запятую/новую строку).
    Сравнение без учёта дефисов и регистра.
    """
    from team_helpers import list_teams as _list_teams, split_notion_db_ids

    r = await db.execute(text("SELECT DISTINCT tenant_id FROM teams_mt"))
    tenant_ids = [row[0] for row in r.all()]

    total = 0
    for tid in tenant_ids:
        teams = await _list_teams(db, tid)
        # Build map: normalized-no-dashes-uppercase -> team_id
        for tm in teams:
            ids = split_notion_db_ids(tm.notion_database_id)
            if not ids:
                continue
            norm_set = [i.replace("-", "").upper() for i in ids]
            placeholders = ", ".join(f":db{i}" for i in range(len(norm_set)))
            params: dict[str, str | int] = {f"db{i}": v for i, v in enumerate(norm_set)}
            params["tid"] = tid
            params["team_id"] = tm.id
            result = await db.execute(
                text(
                    f"""
                    UPDATE transactions
                    SET team_id = :team_id
                    WHERE tenant_id = :tid
                      AND notion_database_id IS NOT NULL
                      AND replace(replace(upper(trim(notion_database_id)), '-', ''), ' ', '')
                          IN ({placeholders})
                    """
                ),
                params,
            )
            total += result.rowcount or 0
    await db.commit()
    return total


async def backfill_notion_database_id_from_notion_api(
    db: AsyncSession,
    tenant_id: int,
    notion_token: str,
    limit: int = 150,
) -> int:
    """
    Для строк с notion_id, но без notion_database_id — запросить Notion API (parent.database_id).
    """
    import httpx

    r = await db.execute(
        select(Transaction.id, Transaction.notion_id)
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.notion_id.isnot(None),
            Transaction.notion_id != "",
            Transaction.notion_database_id.is_(None),
        )
        .limit(limit)
    )
    rows = r.all()
    if not rows:
        return 0

    headers = {
        "Authorization": f"Bearer {notion_token.strip()}",
        "Notion-Version": "2022-06-28",
    }
    updated = 0
    async with httpx.AsyncClient(timeout=25) as client:
        for tx_id, nid in rows:
            raw = (nid or "").strip().replace("-", "")
            if len(raw) != 32:
                continue
            page_id = f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
            try:
                resp = await client.get(
                    f"https://api.notion.com/v1/pages/{page_id}",
                    headers=headers,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                parent = data.get("parent") or {}
                dbid = parent.get("database_id")
                if not dbid:
                    continue
                canon = normalize_notion_db_id(dbid)
                if canon:
                    await db.execute(
                        update(Transaction)
                        .where(Transaction.id == tx_id)
                        .values(notion_database_id=canon)
                    )
                    updated += 1
            except Exception as e:
                logger.debug("notion page fetch skip id=%s: %s", tx_id, e)
                continue
    await db.commit()
    return updated
