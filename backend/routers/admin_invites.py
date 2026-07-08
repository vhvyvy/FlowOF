"""
Admin Invite Flow — owner creates invite links for agency admins/team leads.

Prefix  : /api/v1/admin-invites
Public  : GET /validate/{token}, POST /activate
Owner   : POST /create, GET /, DELETE /{id}
Owner   : PATCH /users/{user_id}/revoke — revoke admin flag
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, hash_password
from database import get_db
from dependencies import require_owner
from models import User

logger = logging.getLogger("flowof.admin_invites")
router = APIRouter(prefix="/api/v1/admin-invites", tags=["admin_invites"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateInviteRequest(BaseModel):
    admin_shift_id: int
    invited_email: Optional[str] = None
    expires_in_days: Optional[int] = 14


class ActivateRequest(BaseModel):
    token: str
    email: str
    password: str
    display_name: str


# ── Owner endpoints ───────────────────────────────────────────────────────────

@router.post("/create")
async def create_invite(
    body: CreateInviteRequest,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Owner creates an invite link for an agency admin."""
    # Verify shift belongs to this tenant
    shift_row = (
        await db.execute(
            text("SELECT id, name FROM shifts_catalog WHERE id = :sid AND tenant_id = :tid"),
            {"sid": body.admin_shift_id, "tid": owner.tenant_id},
        )
    ).fetchone()
    if shift_row is None:
        raise HTTPException(status_code=404, detail="Смена не найдена")

    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.utcnow() + timedelta(days=body.expires_in_days)
        if body.expires_in_days
        else None
    )

    await db.execute(
        text(
            """INSERT INTO admin_invites
               (tenant_id, token, admin_shift_id, invited_email, expires_at)
               VALUES (:tid, :tok, :shift, :email, :exp)"""
        ),
        {
            "tid":   owner.tenant_id,
            "tok":   token,
            "shift": body.admin_shift_id,
            "email": (body.invited_email or "").strip() or None,
            "exp":   expires_at,
        },
    )
    await db.commit()

    frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
    join_url = f"{frontend_url}/admin-join/{token}"

    logger.info("create_invite: tenant=%s shift=%s token=%s", owner.tenant_id, body.admin_shift_id, token[:8])
    return {
        "token":         token,
        "join_url":      join_url,
        "admin_shift_id": body.admin_shift_id,
        "shift_name":    shift_row[1],
    }


@router.get("/")
async def list_invites(
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """List unused (available) admin invites for this tenant."""
    rows = (
        await db.execute(
            text(
                """SELECT i.id, i.token, i.invited_email, i.created_at, i.expires_at,
                          s.name AS shift_name, i.admin_shift_id
                   FROM admin_invites i
                   JOIN shifts_catalog s ON i.admin_shift_id = s.id
                   WHERE i.tenant_id = :tid
                     AND i.used_by_user_id IS NULL
                   ORDER BY i.created_at DESC"""
            ),
            {"tid": owner.tenant_id},
        )
    ).fetchall()

    frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
    return {
        "items": [
            {
                "id":             r[0],
                "token":          r[1],
                "invited_email":  r[2],
                "created_at":     r[3].isoformat() if r[3] else None,
                "expires_at":     r[4].isoformat() if r[4] else None,
                "shift_name":     r[5],
                "admin_shift_id": r[6],
                "join_url":       f"{frontend_url}/admin-join/{r[1]}",
            }
            for r in rows
        ]
    }


@router.delete("/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an unused admin invite."""
    row = (
        await db.execute(
            text(
                "SELECT id FROM admin_invites WHERE id = :iid AND tenant_id = :tid"
                " AND used_by_user_id IS NULL"
            ),
            {"iid": invite_id, "tid": owner.tenant_id},
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Инвайт не найден или уже использован")

    await db.execute(
        text("DELETE FROM admin_invites WHERE id = :iid"),
        {"iid": invite_id},
    )
    await db.commit()


@router.patch("/users/{user_id}/revoke", status_code=status.HTTP_200_OK)
async def revoke_admin_access(
    user_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Toggle is_admin = False for a user (revoke admin role)."""
    user = await db.get(User, user_id)
    if user is None or user.tenant_id != owner.tenant_id:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_admin = False
    await db.commit()
    logger.info("revoke_admin: tenant=%s user=%s", owner.tenant_id, user_id)
    return {"success": True, "user_id": user_id}


# ── Public endpoints (no auth) ────────────────────────────────────────────────

@router.get("/validate/{token}")
async def validate_token(token: str, db: AsyncSession = Depends(get_db)):
    """Validate an admin invite token (public, used by join page)."""
    row = (
        await db.execute(
            text(
                """SELECT i.id, i.used_by_user_id, i.expires_at, i.invited_email,
                          s.name AS shift_name,
                          t.agency_name AS tenant_name
                   FROM admin_invites i
                   JOIN shifts_catalog s ON i.admin_shift_id = s.id
                   JOIN tenants t ON i.tenant_id = t.id
                   WHERE i.token = :tok"""
            ),
            {"tok": token},
        )
    ).fetchone()

    if row is None:
        return {"valid": False, "reason": "not_found"}
    if row[1] is not None:
        return {"valid": False, "reason": "used"}
    if row[2] is not None and row[2] < datetime.utcnow():
        return {"valid": False, "reason": "expired"}

    return {
        "valid":          True,
        "shift_name":     row[4],
        "tenant_name":    row[5],
        "invited_email":  row[3],
    }


@router.post("/activate")
async def activate_invite(
    body: ActivateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new admin user via invite token."""
    row = (
        await db.execute(
            text(
                """SELECT i.id, i.tenant_id, i.admin_shift_id,
                          i.used_by_user_id, i.expires_at, i.invited_email
                   FROM admin_invites i
                   WHERE i.token = :tok"""
            ),
            {"tok": body.token},
        )
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=400, detail="Инвайт не найден")
    if row[3] is not None:
        raise HTTPException(status_code=400, detail="Инвайт уже использован")
    if row[4] is not None and row[4] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Срок действия инвайта истёк")

    invite_id      = row[0]
    tenant_id      = row[1]
    admin_shift_id = row[2]

    email = body.email.lower().strip()
    # Check uniqueness
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    user = User(
        tenant_id=tenant_id,
        email=email,
        hashed_password=hash_password(body.password),
        role="owner",          # same role as owners so they can log in normally
        full_name=body.display_name.strip(),
        is_admin=True,
        admin_shift_id=admin_shift_id,
        active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Mark invite used
    await db.execute(
        text(
            "UPDATE admin_invites SET used_by_user_id = :uid, used_at = NOW() WHERE id = :iid"
        ),
        {"uid": user.id, "iid": invite_id},
    )
    await db.commit()

    access_token = create_access_token(
        tenant_id=tenant_id,
        email=email,
        user_id=user.id,
        role="owner",
    )
    logger.info("activate_invite: tenant=%s user=%s email=%s", tenant_id, user.id, email)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": "owner",
        "is_admin": True,
    }
