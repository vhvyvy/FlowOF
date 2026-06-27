"""Управление аккаунтами чаттеров — owner-only."""
from __future__ import annotations

import logging
import random
import string

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from auth import hash_password
from database import get_db
from dependencies import require_owner
from models import User

logger = logging.getLogger("flowof.manage_chatters")
router = APIRouter(prefix="/api/v1/manage", tags=["manage_chatters"])


def _random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


def _chatter_cond(owner: User) -> dict:
    return {"tid": owner.tenant_id}


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/chatters")
async def list_chatter_accounts(
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Все чаттеры каталога агентства + данные аккаунта если есть."""
    result = await db.execute(
        text(
            """SELECT
                 c.id        AS chatter_id,
                 c.name      AS chatter_name,
                 c.active    AS catalog_active,
                 u.id        AS user_id,
                 u.email,
                 u.full_name,
                 u.active    AS account_active,
                 u.created_at,
                 u.avatar_base64
               FROM chatters c
               LEFT JOIN users u ON u.chatter_id = c.id AND u.tenant_id = :tid AND u.role = 'chatter'
               WHERE c.tenant_id = :tid AND c.active IS NOT FALSE
               ORDER BY c.name ASC"""
        ),
        {"tid": owner.tenant_id},
    )
    rows = []
    for r in result.mappings():
        has_account = r["user_id"] is not None
        rows.append({
            "id":            int(r["user_id"]) if has_account else None,
            "chatter_id":    int(r["chatter_id"]),
            "chatter_name":  r["chatter_name"],
            "email":         r["email"],
            "full_name":     r["full_name"],
            "active":        bool(r["account_active"]) if has_account else False,
            "created_at":    str(r["created_at"]) if r["created_at"] else None,
            "has_account":   has_account,
            "avatar_base64": r["avatar_base64"],
        })
    return {"items": rows}


# ── Reset password ────────────────────────────────────────────────────────────

@router.post("/chatters/{user_id}/reset-password")
async def reset_chatter_password(
    user_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new random password and return it in plaintext (one-time)."""
    # Ensure the target belongs to this tenant and is a chatter
    chk = await db.execute(
        text("SELECT id, email FROM users WHERE id = :uid AND tenant_id = :tid AND role = 'chatter'"),
        {"uid": user_id, "tid": owner.tenant_id},
    )
    row = chk.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Чаттер не найден")

    temp_pw = _random_password()
    hashed  = hash_password(temp_pw)
    await db.execute(
        text("UPDATE users SET hashed_password = :hp WHERE id = :uid"),
        {"hp": hashed, "uid": user_id},
    )
    await db.commit()
    logger.info("owner %d reset password for chatter user_id=%d (%s)", owner.id, user_id, row["email"])
    return {"temp_password": temp_pw}


# ── Activate / Deactivate ─────────────────────────────────────────────────────

async def _set_active(user_id: int, active: bool, owner: User, db: AsyncSession) -> dict:
    chk = await db.execute(
        text("SELECT id FROM users WHERE id = :uid AND tenant_id = :tid AND role = 'chatter'"),
        {"uid": user_id, "tid": owner.tenant_id},
    )
    if not chk.mappings().first():
        raise HTTPException(status_code=404, detail="Чаттер не найден")
    await db.execute(
        text("UPDATE users SET active = :active WHERE id = :uid"),
        {"active": active, "uid": user_id},
    )
    await db.commit()
    return {"success": True, "active": active}


@router.post("/chatters/{user_id}/deactivate")
async def deactivate_chatter(
    user_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _set_active(user_id, False, owner, db)


@router.post("/chatters/{user_id}/activate")
async def activate_chatter(
    user_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _set_active(user_id, True, owner, db)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/chatters/{user_id}")
async def delete_chatter_account(
    user_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Delete the user record. The chatters catalog row is kept to preserve transactions."""
    chk = await db.execute(
        text("SELECT id, chatter_id FROM users WHERE id = :uid AND tenant_id = :tid AND role = 'chatter'"),
        {"uid": user_id, "tid": owner.tenant_id},
    )
    row = chk.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Чаттер не найден")

    # NULL-out any FK references before deletion to avoid constraint errors
    await db.execute(
        text("UPDATE chatter_invites SET created_by_user_id = NULL WHERE created_by_user_id = :uid"),
        {"uid": user_id},
    )
    await db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    await db.commit()
    logger.info("owner %d deleted chatter user_id=%d (chatters row %s kept)", owner.id, user_id, row["chatter_id"])
    return {"success": True}
