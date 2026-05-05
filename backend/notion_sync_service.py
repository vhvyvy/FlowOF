"""
Notion → PostgreSQL: загрузка транзакций из баз данных Notion в таблицу transactions.
Логика полей совместима со scripts/sync_notion_full.py (repo_temp).
"""
from __future__ import annotations

import asyncio
import logging
import os
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import SyncLog, Team, Tenant, Transaction
from team_bootstrap import assign_transactions_by_notion_database
from team_helpers import list_teams, normalize_notion_db_id

logger = logging.getLogger("flowof.notion_sync")

NOTION_VERSION = "2022-06-28"


def _parse_date(val: Any):
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    s = str(val).strip()
    if "T" in s:
        s = s[:10]
    try:
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        return date(y, m, d)
    except Exception:
        return None


def _format_notion_page_id(page_id: str) -> str:
    pid = page_id.replace("-", "")
    if len(pid) != 32:
        return page_id
    return f"{pid[0:8]}-{pid[8:12]}-{pid[12:16]}-{pid[16:20]}-{pid[20:32]}"


async def _page_title(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
    cache: dict[str, str],
) -> str | None:
    if page_id in cache:
        return cache[page_id]
    fmt = _format_notion_page_id(page_id)
    # Как в sync_notion_full.get_page_title: пробуем канонический UUID и сырой id из API
    data: dict | None = None
    for url_id in (fmt, page_id):
        if not url_id:
            continue
        r = await client.get(
            f"https://api.notion.com/v1/pages/{url_id}",
            headers=headers,
            timeout=30.0,
        )
        if r.status_code != 200:
            continue
        data = r.json()
        break
    if not data:
        return None
    for p in data.get("properties", {}).values():
        if p.get("type") == "title" and p.get("title"):
            t = p["title"][0].get("plain_text", "").strip()
            if t:
                cache[page_id] = t
                return t
    return None


def _norm_prop_name(key: Any) -> str:
    return unicodedata.normalize("NFKC", str(key)).strip().lower()


def _legacy_model_property(props: dict) -> dict | None:
    """Как в scripts/sync_notion_full.py: только точные имена, плюс совпадение с .strip() по ключу."""
    for pk in ("Модель", "модель", "Model", "model", "MODEL"):
        for k, v in props.items():
            if str(k).strip() != pk:
                continue
            if isinstance(v, dict) and v.get("type"):
                return v
    return None


def _find_model_property(props: dict) -> dict | None:
    """Колонка модели в разных базах: «Модель», «модель», rollup и т.д."""
    for key in ("Модель", "модель", "Model", "model", "MODEL"):
        p = props.get(key)
        if isinstance(p, dict) and p.get("type"):
            return p
    for key, val in props.items():
        kn = _norm_prop_name(key)
        if ("модел" in kn) or kn == "model":
            if isinstance(val, dict) and val.get("type"):
                return val
    return None


def _text_from_rich_blocks(blocks: list | None) -> str | None:
    if not blocks:
        return None
    parts = []
    for b in blocks:
        if isinstance(b, dict):
            parts.append((b.get("plain_text") or "").strip())
    s = " ".join(x for x in parts if x).strip()
    return s or None


async def _relation_ids_via_property_api(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
    property_id: str,
) -> list[str]:
    """
    Полный список ID связанных страниц для relation.
    Notion в ответе query/retrieve page может отдать пустой relation[] или обрезать >25;
    для точного списка используется GET /v1/pages/{id}/properties/{property_id}.
    """
    fmt = _format_notion_page_id(page_id)
    prop_path = quote(property_id, safe="")
    url = f"https://api.notion.com/v1/pages/{fmt}/properties/{prop_path}"
    ids: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {}
        if cursor:
            params["start_cursor"] = cursor
        r = await client.get(url, headers=headers, params=params, timeout=30.0)
        if r.status_code != 200:
            logger.debug(
                "notion relation property retrieve failed page=%s prop=%s status=%s",
                fmt[:8],
                property_id,
                r.status_code,
            )
            break
        data = r.json()
        if data.get("object") == "error":
            logger.debug("notion relation property error: %s", data.get("message"))
            break
        if data.get("object") == "list":
            for item in data.get("results") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "relation":
                    continue
                rel = item.get("relation") or {}
                rid = rel.get("id") if isinstance(rel, dict) else None
                if rid:
                    ids.append(rid)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
            await asyncio.sleep(0.05)
            continue
        if isinstance(data, dict) and data.get("type") == "relation":
            rel = data.get("relation") or {}
            rid = rel.get("id") if isinstance(rel, dict) else None
            if rid:
                ids.append(rid)
        break
    return ids


async def _relation_target_page_ids(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    model_prop: dict,
    page_id: str | None,
) -> list[str]:
    """ID страниц из relation: inline в ответе + при >25 или пустом inline — через property API."""
    ids: list[str] = []
    rel = model_prop.get("relation")
    if isinstance(rel, list):
        for item in rel:
            if isinstance(item, dict) and item.get("id"):
                ids.append(item["id"])
    if model_prop.get("type") != "relation":
        return ids
    prop_nid = model_prop.get("id")
    if not page_id or not prop_nid:
        return ids
    must_fetch = (model_prop.get("has_more") is True) or (not ids)
    if not must_fetch:
        return ids
    fetched = await _relation_ids_via_property_api(client, headers, page_id, str(prop_nid))
    return fetched or ids


async def _model_name_from_property(
    model_prop: dict,
    client: httpx.AsyncClient,
    headers: dict[str, str],
    model_cache: dict[str, str],
    page_id: str | None = None,
) -> str | None:
    """Достаёт имя модели для relation / select / rollup / formula и др."""
    if not isinstance(model_prop, dict):
        return None
    t = model_prop.get("type")

    if t == "relation":
        rids = await _relation_target_page_ids(client, headers, model_prop, page_id)
        if rids:
            name = await _page_title(client, headers, rids[0], model_cache)
            return name or "—"
        return None

    if t == "rollup":
        roll = model_prop.get("rollup") or {}
        rt = roll.get("type")
        if rt == "array" and roll.get("array"):
            for item in roll["array"]:
                if not isinstance(item, dict):
                    continue
                it = item.get("type")
                if it == "title" and item.get("title"):
                    tx = _text_from_rich_blocks(item["title"])
                    if tx:
                        return tx
                if it == "rich_text" and item.get("rich_text"):
                    tx = _text_from_rich_blocks(item["rich_text"])
                    if tx:
                        return tx
                if it == "select" and item.get("select"):
                    n = (item["select"].get("name") or "").strip()
                    if n:
                        return n
        if rt == "string" and roll.get("string") is not None:
            s = str(roll.get("string") or "").strip()
            return s or None

    if t == "formula":
        f = model_prop.get("formula") or {}
        ft = f.get("type")
        if ft == "string" and f.get("string") is not None:
            s = str(f.get("string") or "").strip()
            return s or None

    if t == "select" and model_prop.get("select"):
        return (model_prop["select"].get("name") or "").strip() or None
    if t == "rich_text" and model_prop.get("rich_text"):
        return _text_from_rich_blocks(model_prop["rich_text"])
    if t == "title" and model_prop.get("title"):
        return _text_from_rich_blocks(model_prop["title"])
    if t == "multi_select" and model_prop.get("multi_select"):
        return (model_prop["multi_select"][0].get("name") or "").strip() or None
    if t == "status" and model_prop.get("status"):
        return (model_prop["status"].get("name") or "").strip() or None

    return None


async def _parse_row(
    row: dict,
    shift_type: str,
    client: httpx.AsyncClient,
    headers: dict[str, str],
    model_cache: dict[str, str],
    chatter_cache: dict[str, str],
    shift_cache: dict[str, str],
) -> tuple[Any, ...]:
    notion_page_id = row.get("id")
    props = row.get("properties", {})

    # ── Amount: exact names first, then fuzzy (contains "сумм" / "amount" / "оплат" / "выход") ──
    amount_prop = (
        props.get("Сумма выхода")
        or props.get("Сумма")
        or props.get("Amount")
        or props.get("Amount Spent")
        or None
    )
    if amount_prop is None:
        for k, v in props.items():
            kn = _norm_prop_name(k)
            if isinstance(v, dict) and any(h in kn for h in ("сумм", "amount", "оплат", "выход")):
                amount_prop = v
                break
    amount_prop = amount_prop or {}

    def _extract_number(p: dict) -> float:
        t = p.get("type")
        try:
            if t == "number":
                return float(p.get("number") or 0)
            if t == "formula":
                f = p.get("formula") or {}
                if f.get("type") == "number":
                    return float(f.get("number") or 0)
            if t == "rollup":
                r = p.get("rollup") or {}
                if r.get("type") == "number":
                    return float(r.get("number") or 0)
        except (TypeError, ValueError):
            pass
        return 0.0

    try:
        amount = _extract_number(amount_prop) if isinstance(amount_prop, dict) else 0.0
    except (TypeError, ValueError):
        amount = 0.0

    # ── Date ──
    date_prop = props.get("Date") or props.get("date") or props.get("Transaction Date") or None
    if date_prop is None:
        for k, v in props.items():
            kn = _norm_prop_name(k)
            if isinstance(v, dict) and v.get("type") == "date" and any(h in kn for h in ("date", "дата")):
                date_prop = v
                break
    date_prop = date_prop or {}
    date_obj = (date_prop or {}).get("date") if isinstance(date_prop, dict) else None
    date_val = _parse_date(date_obj.get("start") if date_obj else None)

    # Сначала как в sync_notion_full (в т.ч. ключи с лишними пробелами), затем расширенный поиск
    model_prop = _legacy_model_property(props) or _find_model_property(props)
    model_name = None
    if model_prop:
        model_name = await _model_name_from_property(
            model_prop, client, headers, model_cache, notion_page_id
        )
    # Несколько колонок с «модел» в названии (модель / Модель общее)
    if not model_name:
        for key, val in props.items():
            if not isinstance(val, dict) or val is model_prop:
                continue
            kn = _norm_prop_name(key)
            if "модел" not in kn:
                continue
            model_name = await _model_name_from_property(
                val, client, headers, model_cache, notion_page_id
            )
            if model_name:
                break
    # Если основная колонка — relation с пустым API, но есть rollup-копия имени
    if not model_name:
        for key, val in props.items():
            if not isinstance(val, dict) or val.get("type") != "rollup":
                continue
            if val is model_prop:
                continue
            model_name = await _model_name_from_property(
                val, client, headers, model_cache, notion_page_id
            )
            if model_name:
                break

    chatter = None
    # Сначала точные имена, затем fuzzy (contains "чатт" or "chatt")
    cp = (
        props.get("Чаттер")
        or props.get("Chatter")
        or props.get("чаттер")
        or props.get("chatter")
        or None
    )
    if cp is None:
        for k, v in props.items():
            kn = _norm_prop_name(k)
            if isinstance(v, dict) and any(h in kn for h in ("чатт", "chatt")):
                cp = v
                break
    cp = cp or {}
    ct = cp.get("type") if isinstance(cp, dict) else None

    def _text_from_array(arr: list) -> str | None:
        for item in arr:
            t = (item.get("plain_text") or "").strip()
            if t:
                return t
        return None

    if ct == "rich_text":
        chatter = _text_from_array(cp.get("rich_text") or [])
    elif ct == "title":
        chatter = _text_from_array(cp.get("title") or [])
    elif ct == "select" and cp.get("select"):
        chatter = (cp["select"].get("name") or "").strip() or None
    elif ct == "multi_select" and cp.get("multi_select"):
        chatter = (cp["multi_select"][0].get("name") or "").strip() or None
    elif ct == "people" and cp.get("people"):
        p0 = cp["people"][0]
        chatter = (p0.get("name") or p0.get("id") or "").strip() or None
    elif ct == "relation" and cp.get("relation"):
        chatter = await _page_title(client, headers, cp["relation"][0]["id"], chatter_cache)
    elif ct == "formula":
        f = cp.get("formula") or {}
        ft = f.get("type")
        if ft == "string":
            chatter = (f.get("string") or "").strip() or None
        elif ft == "number":
            v = f.get("number")
            chatter = str(int(v)) if v is not None else None
    elif ct == "rollup":
        ro = cp.get("rollup") or {}
        arr = ro.get("array") or []
        for item in arr:
            it = item.get("type")
            if it == "rich_text":
                chatter = _text_from_array(item.get("rich_text") or [])
            elif it == "select":
                s = item.get("select") or {}
                chatter = (s.get("name") or "").strip() or None
            if chatter:
                break

    def _extract_shift_from_prop(prop):
        if not isinstance(prop, dict):
            return None, None
        ptype = prop.get("type")
        if ptype == "relation" and prop.get("relation"):
            rid = prop["relation"][0].get("id")
            if rid:
                return rid, "relation"
        if ptype == "select" and prop.get("select"):
            name = (prop["select"].get("name") or "").strip()
            if name:
                return name, "select"
        if ptype == "multi_select" and prop.get("multi_select"):
            name = (prop["multi_select"][0].get("name") or "").strip()
            if name:
                return name, "multi_select"
        if ptype == "rich_text" and prop.get("rich_text"):
            txt = (prop["rich_text"][0].get("plain_text") or "").strip()
            if txt:
                return txt, "rich_text"
        if ptype == "title" and prop.get("title"):
            txt = (prop["title"][0].get("plain_text") or "").strip()
            if txt:
                return txt, "title"
        if ptype == "people" and prop.get("people"):
            name = (prop["people"][0].get("name") or "").strip()
            if name:
                return name, "people"
        return None, None

    shift_val, shift_kind = None, None
    preferred = "relation" if shift_type == "relation" else "select"
    fallback = "select" if preferred == "relation" else "relation"
    key_hints = ("смен", "shift", "admin", "админ")
    named_props = [props.get("Смена"), props.get("Shift"), props.get("Admin"), props.get("Админ")]
    for target_kind in (preferred, fallback):
        for p in named_props:
            val, kind = _extract_shift_from_prop(p)
            if val and kind and (
                (target_kind == "relation" and kind == "relation")
                or (target_kind != "relation" and kind != "relation")
            ):
                shift_val, shift_kind = val, kind
                break
        if shift_val:
            break
    if not shift_val:
        for target_kind in (preferred, fallback):
            for key, prop in props.items():
                lname = str(key).strip().lower()
                if not any(h in lname for h in key_hints):
                    continue
                val, kind = _extract_shift_from_prop(prop)
                if val and kind and (
                    (target_kind == "relation" and kind == "relation")
                    or (target_kind != "relation" and kind != "relation")
                ):
                    shift_val, shift_kind = val, kind
                    break
            if shift_val:
                break

    shift_id = shift_val
    shift_name = None
    if shift_val and shift_kind == "relation":
        shift_name = await _page_title(client, headers, shift_val, shift_cache)
    elif shift_val:
        shift_name = shift_val

    return date_val, model_name, chatter, amount, shift_id, shift_name


async def _resolve_page_to_nested_database_id(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
) -> str | None:
    """Если передан URL страницы с вложенной базой — вернуть id базы (как sync_notion_full._resolve_page_to_database_id)."""
    block_id = page_id.replace("-", "")
    r = await client.get(
        f"https://api.notion.com/v1/blocks/{block_id}/children",
        headers=headers,
        params={"page_size": 50},
        timeout=20.0,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("object") == "error":
        return None
    for block in data.get("results") or []:
        if block.get("type") == "child_database":
            bid = block.get("id")
            if bid:
                return bid
    return None


async def _query_all_pages(
    client: httpx.AsyncClient,
    headers: dict,
    database_id: str,
    *,
    _retried_resolve: bool = False,
) -> list[dict]:
    out: list[dict] = []
    cursor = None
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    while True:
        body: dict = {}
        if cursor:
            body["start_cursor"] = cursor
        r = await client.post(url, headers=headers, json=body, timeout=60.0)
        data = r.json()
        if data.get("object") == "error":
            msg = str(data.get("message") or "")
            if (
                not _retried_resolve
                and ("page, not a database" in msg or "not a database" in msg.lower())
            ):
                nested = await _resolve_page_to_nested_database_id(client, headers, database_id)
                if nested:
                    canon = normalize_notion_db_id(nested) or nested
                    logger.info(
                        "notion: id %s was a page, using nested database %s",
                        database_id[:8],
                        canon[:8],
                    )
                    return await _query_all_pages(client, headers, canon, _retried_resolve=True)
            logger.warning("notion query error db=%s: %s", database_id[:8], data.get("message"))
            break
        out.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        await asyncio.sleep(0.35)
    return out


def _collect_database_ids(teams: list[Team]) -> list[str]:
    ids: list[str] = []
    env_main = (os.getenv("NOTION_TRANSACTIONS_DATABASE_ID") or "").strip()
    if env_main:
        n = normalize_notion_db_id(env_main)
        if n:
            ids.append(n)
    for tm in teams:
        if tm.notion_database_id:
            n = normalize_notion_db_id(tm.notion_database_id)
            if n and n not in ids:
                ids.append(n)
    return ids


async def sync_notion_transactions_for_tenant(
    db: AsyncSession,
    tenant_id: int,
    notion_token: str,
    *,
    shift_type: str = "relation",
) -> dict[str, int]:
    """
    Импорт страниц из всех настроенных баз Notion в transactions.
    Возвращает счётчики: inserted, updated, skipped, pages, databases.

    Env: NOTION_SYNC_ALLOW_EMPTY_MODEL=1 — импортировать строки без разрешённой модели с model=\"—\"
    (если интеграция не видит связанную базу моделей; лучше выдать доступ в Notion).
    """
    token = notion_token.strip()
    if not token:
        raise ValueError("notion_token пустой")

    teams = await list_teams(db, tenant_id)
    db_ids = _collect_database_ids(teams)
    if not db_ids:
        raise ValueError(
            "Нет ID баз Notion: задайте NOTION_TRANSACTIONS_DATABASE_ID на Railway "
            "или notion_database_id у команд в /api/v1/teams"
        )

    sync_started = datetime.utcnow()
    sync_log = SyncLog(
        tenant_id=tenant_id,
        source_type="notion",
        started_at=sync_started,
        status="running",
        rows_imported=0,
        rows_skipped=0,
    )
    db.add(sync_log)
    await db.flush()

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    inserted = updated = skipped = 0
    skipped_no_model = 0
    skipped_parse = 0
    model_cache: dict[str, str] = {}
    chatter_cache: dict[str, str] = {}
    shift_cache: dict[str, str] = {}

    allow_empty_model = os.getenv("NOTION_SYNC_ALLOW_EMPTY_MODEL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    async with httpx.AsyncClient() as client:
        for raw_db in db_ids:
            canon = normalize_notion_db_id(raw_db) or raw_db
            pages = await _query_all_pages(client, headers, canon)
            for row in pages:
                notion_id = row.get("id")
                if not notion_id:
                    continue
                try:
                    parsed = await _parse_row(
                        row,
                        shift_type,
                        client,
                        headers,
                        model_cache,
                        chatter_cache,
                        shift_cache,
                    )
                    date_val, model_name, chatter, amount, shift_id, shift_name = parsed
                    # Диагностика: если chatter не найден — логируем свойства строки
                    if chatter is None:
                        props_debug = row.get("properties") or {}
                        chatter_keys = {
                            k: {"type": v.get("type") if isinstance(v, dict) else type(v).__name__}
                            for k, v in props_debug.items()
                        }
                        logger.warning(
                            "chatter=None for page %s | props: %s",
                            (notion_id or "")[:8],
                            chatter_keys,
                        )
                except Exception as e:
                    logger.debug("parse row skip: %s", e)
                    skipped += 1
                    skipped_parse += 1
                    continue
                if not model_name or not str(model_name).strip():
                    if allow_empty_model:
                        model_name = "—"
                    else:
                        skipped += 1
                        skipped_no_model += 1
                        continue

                synced_at = datetime.utcnow()
                stmt = select(Transaction).where(
                    Transaction.tenant_id == tenant_id,
                    Transaction.notion_id == notion_id,
                )
                r = await db.execute(stmt)
                existing = r.scalar_one_or_none()
                if existing:
                    existing.date = date_val
                    existing.model = model_name
                    existing.chatter = chatter
                    existing.amount = Decimal(str(amount))
                    existing.shift_id = shift_id
                    existing.shift_name = shift_name
                    existing.notion_database_id = canon
                    existing.synced_at = synced_at
                    updated += 1
                else:
                    db.add(
                        Transaction(
                            tenant_id=tenant_id,
                            notion_id=notion_id,
                            date=date_val,
                            model=model_name,
                            chatter=chatter,
                            amount=Decimal(str(amount)),
                            shift_id=shift_id,
                            shift_name=shift_name,
                            notion_database_id=canon,
                            synced_at=synced_at,
                        )
                    )
                    inserted += 1
            await asyncio.sleep(0.2)

    fin = datetime.utcnow()
    sync_log.finished_at = fin
    sync_log.status = "success"
    sync_log.rows_imported = inserted + updated
    sync_log.rows_skipped = skipped
    await db.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(last_sync_at=fin)
    )

    await db.commit()
    n = await assign_transactions_by_notion_database(db)
    logger.info(
        "notion sync tenant=%s inserted=%s updated=%s skipped=%s assign=%s",
        tenant_id,
        inserted,
        updated,
        skipped,
        n,
    )
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "skipped_no_model": skipped_no_model,
        "skipped_parse": skipped_parse,
        "databases": len(db_ids),
        "assigned_rows": n,
    }
