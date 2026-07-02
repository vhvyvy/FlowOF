import os
import logging
from calendar import monthrange
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from database import get_db
from dependencies import get_current_tenant
from models import Tenant
from auth import hash_password
from schemas import TenantCreate, TenantOut, TenantPasswordUpdate, AdminTenantListItem, AdminTenantUpdate

logger = logging.getLogger("flowof.admin")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


# ── Зависимости ───────────────────────────────────────────────────────────────

def _require_secret(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    """Старый метод через статичный секрет (для CLI/скриптов)."""
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def _require_is_admin(
    tenant: Tenant = Depends(get_current_tenant),
) -> Tenant:
    """JWT-авторизация: тенант должен иметь is_admin = True."""
    if not getattr(tenant, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для администраторов",
        )
    return tenant


# ── Эндпоинты для фронт-панели (JWT + is_admin) ───────────────────────────────

@router.get("/tenants", response_model=list[AdminTenantListItem])
async def list_tenants_admin(
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """Список всех тенантов для фронт-панели администратора."""
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return result.scalars().all()


@router.get("/tenants/{tenant_id}", response_model=AdminTenantListItem)
async def get_tenant_detail(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=AdminTenantListItem)
async def update_tenant(
    tenant_id: int,
    body: AdminTenantUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """Изменить plan / active / is_admin тенанта."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if body.plan is not None:
        if body.plan not in ("basic", "pro"):
            raise HTTPException(status_code=422, detail="plan должен быть 'basic' или 'pro'")
        tenant.plan = body.plan
    if body.active is not None:
        tenant.active = body.active
    if body.is_admin is not None:
        tenant.is_admin = body.is_admin

    await db.commit()
    await db.refresh(tenant)
    logger.info("Admin updated tenant=%d plan=%s active=%s", tenant_id, tenant.plan, tenant.active)
    return tenant


@router.delete("/tenants/{tenant_id}", status_code=204)
async def deactivate_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """Деактивировать тенанта (soft delete)."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.active = False
    await db.commit()
    logger.info("Admin deactivated tenant=%d", tenant_id)


# ── Устаревшие эндпоинты через X-Admin-Secret (оставлены для CLI) ─────────────

@router.post("/tenants", response_model=TenantOut, status_code=201, include_in_schema=False)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_secret),
):
    existing = await db.execute(select(Tenant).where(Tenant.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    slug = body.email.split("@")[0].lower().replace(".", "-")
    tenant = Tenant(
        name=body.name,
        slug=slug,
        email=body.email.lower().strip(),
        password_hash=hash_password(body.password),
        plan=body.plan,
        notion_token=body.notion_token,
        onlymonster_key=body.onlymonster_key,
        onlymonster_account_ids=body.onlymonster_account_ids,
        openai_key=body.openai_key,
        active=True,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    logger.info("Created tenant id=%d email=%s", tenant.id, tenant.email)
    return tenant


@router.patch("/tenants/{tenant_id}/password", status_code=204, include_in_schema=False)
async def update_password(
    tenant_id: int,
    body: TenantPasswordUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_secret),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.password_hash = hash_password(body.password)
    await db.commit()
    logger.info("Password updated for tenant=%d", tenant_id)


@router.patch("/tenants/{tenant_id}/toggle", response_model=TenantOut, include_in_schema=False)
async def toggle_active(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_secret),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.active = not tenant.active
    await db.commit()
    await db.refresh(tenant)
    logger.info("Tenant=%d active=%s", tenant_id, tenant.active)
    return tenant


# ── Notion ↔ DB diff (READ-ONLY diagnostic) ───────────────────────────────────

def _norm_chatter(name: str | None) -> str:
    """Normalise chatter name: strip, drop leading '@', lowercase."""
    if not name:
        return ""
    return str(name).strip().lstrip("@").strip().lower()


@router.get("/notion-diff")
async def notion_diff(
    tenant_id: int = Query(..., description="ID тенанта"),
    chatter: str = Query(..., description="Имя чаттера (без @)"),
    year: int = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """READ-ONLY сверка транзакций Notion ↔ БД для конкретного чаттера за месяц."""
    import asyncio
    import httpx
    from notion_sync_service import (
        _query_all_pages, _parse_row, _collect_database_ids, NOTION_VERSION,
    )
    from team_helpers import list_teams, normalize_notion_db_id

    # ── Fetch target tenant ────────────────────────────────────────────────────
    target_tenant = await db.get(Tenant, tenant_id)
    if not target_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    notion_token = (target_tenant.notion_token or "").strip()
    if not notion_token:
        raise HTTPException(status_code=400, detail="У тенанта нет Notion token")

    chatter_norm = _norm_chatter(chatter)
    if not chatter_norm:
        raise HTTPException(status_code=422, detail="Параметр chatter не может быть пустым")

    last_day = monthrange(year, month)[1]
    period_start = date(year, month, 1)
    period_end   = date(year, month, last_day)

    # ── 1. Pull rows from Notion ───────────────────────────────────────────────
    teams = await list_teams(db, tenant_id)
    db_ids = _collect_database_ids(teams)
    if not db_ids:
        raise HTTPException(status_code=400, detail="Нет ID баз Notion у тенанта")

    headers_n = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    notion_rows: list[dict[str, Any]] = []
    model_cache: dict[str, str] = {}
    chatter_cache: dict[str, str] = {}
    shift_cache: dict[str, str] = {}

    async with httpx.AsyncClient() as client:
        for raw_db in db_ids:
            canon = normalize_notion_db_id(raw_db) or raw_db
            pages = await _query_all_pages(client, headers_n, canon)
            for row in pages:
                notion_id = row.get("id")
                if not notion_id:
                    continue
                try:
                    parsed = await _parse_row(
                        row, "relation", client, headers_n,
                        model_cache, chatter_cache, shift_cache,
                    )
                    date_val, model_name, chatter_name, amount, shift_id, shift_name = parsed
                except Exception:
                    continue

                # Filter by period
                if date_val is None:
                    continue
                if not (period_start <= date_val <= period_end):
                    continue

                # Filter by chatter (normalised)
                if _norm_chatter(chatter_name) != chatter_norm:
                    continue

                notion_rows.append({
                    "notion_id": notion_id,
                    "date":      str(date_val),
                    "model":     model_name or "",
                    "shift":     shift_name or "",
                    "amount":    round(float(amount or 0), 2),
                })

    # ── 2. Pull rows from DB ───────────────────────────────────────────────────
    db_result = await db.execute(
        text(
            """SELECT t.id, t.notion_id, t.amount, t.model, t.chatter,
                      t.shift_name, t.date
               FROM transactions t
               WHERE t.tenant_id = :tid
                 AND t.date >= :start AND t.date <= :end
                 AND (
                   t.chatter_id IN (
                     SELECT id FROM chatters
                     WHERE tenant_id = :tid
                       AND LOWER(TRIM(LTRIM(name, '@'))) = :cn
                   )
                   OR LOWER(TRIM(LTRIM(COALESCE(t.chatter, ''), '@'))) = :cn
                 )
               ORDER BY t.date"""
        ),
        {"tid": tenant_id, "start": period_start, "end": period_end, "cn": chatter_norm},
    )
    db_rows_raw = list(db_result.mappings())

    db_by_notion_id: dict[str, dict] = {}
    db_no_notion_id: list[dict] = []
    for r in db_rows_raw:
        nid = r.get("notion_id")
        entry = {
            "id":       int(r["id"]),
            "notion_id": nid,
            "date":     str(r["date"]),
            "model":    r.get("model") or "",
            "amount":   round(float(r.get("amount") or 0), 2),
        }
        if nid:
            # A DB row may have a composite notion_id like "prefix:0" → extract raw page id
            raw_nid = nid.split(":")[0] if ":" in nid else nid
            db_by_notion_id[raw_nid] = entry
        else:
            db_no_notion_id.append(entry)

    # ── 3. Match ───────────────────────────────────────────────────────────────
    matched_ok_count = 0
    amount_mismatch: list[dict] = []
    notion_only: list[dict] = []

    notion_ids_seen: set[str] = set()

    for nr in sorted(notion_rows, key=lambda x: x["date"]):
        nid = nr["notion_id"]
        # strip hyphens for loose matching
        nid_clean = nid.replace("-", "")
        matched = None
        for key in (nid, nid_clean):
            if key in db_by_notion_id:
                matched = db_by_notion_id[key]
                notion_ids_seen.add(key)
                break

        if matched is None:
            notion_only.append(nr)
        elif abs(matched["amount"] - nr["amount"]) < 0.005:
            matched_ok_count += 1
        else:
            amount_mismatch.append({
                "notion_id":     nid,
                "date":          nr["date"],
                "model":         nr["model"],
                "shift":         nr["shift"],
                "notion_amount": nr["amount"],
                "db_amount":     matched["amount"],
                "diff":          round(matched["amount"] - nr["amount"], 2),
            })

    # DB rows whose notion_id was NOT matched + rows without notion_id
    db_only: list[dict] = []
    for key, entry in db_by_notion_id.items():
        if key not in notion_ids_seen:
            db_only.append(entry)
    db_only.extend(db_no_notion_id)
    db_only.sort(key=lambda x: x["date"])

    notion_sum = round(sum(r["amount"] for r in notion_rows), 2)
    db_sum     = round(sum(float(r.get("amount", 0)) for r in db_rows_raw), 2)

    logger.info(
        "notion-diff tenant=%d chatter=%r %d/%d: notion=%d db=%d",
        tenant_id, chatter, year, month, len(notion_rows), len(db_rows_raw),
    )

    return {
        "matched_ok":      matched_ok_count,
        "amount_mismatch": sorted(amount_mismatch, key=lambda x: x["date"]),
        "notion_only":     sorted(notion_only,     key=lambda x: x["date"]),
        "db_only":         sorted(db_only,         key=lambda x: x["date"]),
        "totals": {
            "notion_sum":   notion_sum,
            "db_sum":       db_sum,
            "diff":         round(db_sum - notion_sum, 2),
            "notion_count": len(notion_rows),
            "db_count":     len(db_rows_raw),
        },
    }


# ── Catalog duplicates diagnostic ────────────────────────────────────────────

@router.get("/catalog-duplicates")
async def catalog_duplicates(
    tenant_id: int = Query(...),
    secret: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    x_admin_secret: str | None = Header(None, alias="X-Admin-Secret"),
):
    if not ADMIN_SECRET or (x_admin_secret != ADMIN_SECRET and secret != ADMIN_SECRET):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    """
    Read-only: найти записи с дублирующимся name внутри одного tenant_id в трёх
    каталожных таблицах (models, chatters, shifts_catalog).
    Ничего не меняет, только SELECT.
    """

    async def _find_dupes(table: str, fk_col: str) -> list[dict]:
        # Найти имена с COUNT > 1
        dup_names_q = await db.execute(
            text(
                f"""
                SELECT name
                FROM {table}
                WHERE tenant_id = :tid
                GROUP BY name
                HAVING COUNT(*) > 1
                ORDER BY name
                """
            ),
            {"tid": tenant_id},
        )
        dup_names = [r[0] for r in dup_names_q.all()]
        if not dup_names:
            return []

        groups: list[dict] = []
        for name in dup_names:
            rows_q = await db.execute(
                text(
                    f"""
                    SELECT c.id, c.active,
                           COUNT(t.id) AS tx_count
                    FROM {table} c
                    LEFT JOIN transactions t
                           ON t.{fk_col} = c.id
                          AND t.tenant_id = :tid
                    WHERE c.tenant_id = :tid
                      AND c.name = :name
                    GROUP BY c.id, c.active
                    ORDER BY c.id
                    """
                ),
                {"tid": tenant_id, "name": name},
            )
            entries = [
                {"id": r[0], "active": r[1], "tx_count": r[2]}
                for r in rows_q.all()
            ]
            groups.append({"name": name, "entries": entries})

        return groups

    models_dupes   = await _find_dupes("models",          "model_id")
    chatters_dupes = await _find_dupes("chatters",         "chatter_id")
    shifts_dupes   = await _find_dupes("shifts_catalog",   "shift_catalog_id")

    total = len(models_dupes) + len(chatters_dupes) + len(shifts_dupes)

    return {
        "tenant_id": tenant_id,
        "total_duplicate_names": total,
        "models":         {"duplicate_count": len(models_dupes),   "groups": models_dupes},
        "chatters":       {"duplicate_count": len(chatters_dupes),  "groups": chatters_dupes},
        "shifts_catalog": {"duplicate_count": len(shifts_dupes),    "groups": shifts_dupes},
    }
