"""Notion -> expenses table sync (optional separate DB)."""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime

from models import AppSetting, Expense, SyncLog
from notion_sync_service import NOTION_VERSION, _norm_prop_name, _parse_date
from team_helpers import normalize_notion_db_id

logger = logging.getLogger("flowof.notion_expenses")


async def _cfg_expense_db_ids(db: AsyncSession, tenant_id: int) -> list[str]:
    r = await db.execute(
        select(AppSetting.value).where(
            AppSetting.tenant_id == tenant_id,
            AppSetting.key == "notion_expenses_database_ids",
        )
    )
    raw = (r.scalar_one_or_none() or "").strip()
    if not raw:
        raw = (os.getenv("NOTION_EXPENSES_DATABASE_ID") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        # normalize_notion_db_id handles full URLs, UUID with dashes, bare hex32
        canon = normalize_notion_db_id(p)
        if not canon:
            continue
        # Notion API принимает UUID без дефисов или с — оба варианта работают.
        # Храним без дефисов для единообразия.
        canon_nodash = canon.replace("-", "")
        if canon_nodash not in [x.replace("-", "") for x in out]:
            out.append(canon)
    return out


def _pick_prop(props: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for k, v in props.items():
        kn = _norm_prop_name(k)
        if any(x in kn for x in keys):
            if isinstance(v, dict) and v.get("type"):
                return v
    return None


def _prop_text(p: dict[str, Any] | None) -> str | None:
    if not p:
        return None
    t = p.get("type")
    if t == "title":
        arr = p.get("title") or []
        return "".join((x.get("plain_text") or "") for x in arr).strip() or None
    if t == "rich_text":
        arr = p.get("rich_text") or []
        return "".join((x.get("plain_text") or "") for x in arr).strip() or None
    if t == "select":
        s = p.get("select") or {}
        return (s.get("name") or "").strip() or None
    if t == "multi_select":
        arr = p.get("multi_select") or []
        return ", ".join((x.get("name") or "").strip() for x in arr if (x.get("name") or "").strip()) or None
    if t == "number":
        n = p.get("number")
        return str(n) if n is not None else None
    return None


def _prop_amount(p: dict[str, Any] | None) -> Decimal | None:
    if not p:
        return None
    if p.get("type") == "number":
        n = p.get("number")
        if n is None:
            return None
        return Decimal(str(n))
    txt = _prop_text(p)
    if not txt:
        return None
    cleaned = txt.replace(" ", "").replace(",", ".")
    for ch in ("$", "€", "₽"):
        cleaned = cleaned.replace(ch, "")
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _prop_date(p: dict[str, Any] | None):
    if not p:
        return None
    if p.get("type") == "date":
        d = (p.get("date") or {}).get("start")
        return _parse_date(d)
    return _parse_date(_prop_text(p))


async def _query_db_pages(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    database_id: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        payload: dict[str, Any] = {}
        if cursor:
            payload["start_cursor"] = cursor
        r = await client.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=headers,
            json=payload,
            timeout=40.0,
        )
        if r.status_code != 200:
            raise ValueError(f"Notion DB query failed ({database_id[:8]}): {r.text[:200]}")
        data = r.json()
        out.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


async def sync_notion_expenses_for_tenant(
    db: AsyncSession,
    tenant_id: int,
    notion_token: str,
) -> dict[str, int]:
    db_ids = await _cfg_expense_db_ids(db, tenant_id)
    if not db_ids:
        return {"inserted": 0, "updated": 0, "skipped": 0, "databases": 0}

    started = SyncLog(
        tenant_id=tenant_id,
        source_type="notion_expenses",
        status="running",
        rows_imported=0,
        rows_skipped=0,
    )
    db.add(started)
    await db.flush()

    headers = {
        "Authorization": f"Bearer {notion_token.strip()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    inserted = updated = skipped = 0

    async with httpx.AsyncClient() as client:
        for dbid in db_ids:
            pages = await _query_db_pages(client, headers, dbid)
            for page in pages:
                pid = page.get("id")
                props = page.get("properties") or {}
                if not pid or not isinstance(props, dict):
                    skipped += 1
                    continue

                date_p = _pick_prop(props, ("дата", "date", "day"))
                amount_p = _pick_prop(props, ("сумм", "amount", "cost", "расход"))
                category_p = _pick_prop(props, ("катег", "category", "type"))
                model_p = _pick_prop(props, ("модел", "model"))
                vendor_p = _pick_prop(props, ("vendor", "постав", "контраг", "кому"))
                pay_p = _pick_prop(props, ("payment", "оплат", "метод", "method"))

                d = _prop_date(date_p)
                amt = _prop_amount(amount_p)
                if d is None or amt is None:
                    skipped += 1
                    continue

                cat = _prop_text(category_p)
                model = _prop_text(model_p)
                vendor = _prop_text(vendor_p)
                payment_method = _prop_text(pay_p)

                r = await db.execute(
                    select(Expense).where(
                        Expense.tenant_id == tenant_id,
                        Expense.notion_id == pid,
                    )
                )
                ex = r.scalar_one_or_none()
                if ex:
                    ex.date = d
                    ex.amount = amt
                    ex.category = cat
                    ex.model = model
                    ex.vendor = vendor
                    ex.payment_method = payment_method
                    updated += 1
                else:
                    db.add(
                        Expense(
                            tenant_id=tenant_id,
                            notion_id=pid,
                            date=d,
                            amount=amt,
                            category=cat,
                            model=model,
                            vendor=vendor,
                            payment_method=payment_method,
                        )
                    )
                    inserted += 1

    started.finished_at = datetime.utcnow()
    started.status = "success"
    started.rows_imported = inserted + updated
    started.rows_skipped = skipped
    await db.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "databases": len(db_ids)}
