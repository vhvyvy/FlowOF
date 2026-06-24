"""Система инвайтов — owner приглашает чаттера в личный кабинет."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, hash_password
from database import get_db
from dependencies import require_owner
from models import CatalogChatter, ChatterInvite, User

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


# ─── Owner: управление инвайтами ────────────────────────────────────────────


@router.post("/chatter/{chatter_id}")
async def create_chatter_invite(
    chatter_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Owner создаёт инвайт-ссылку для чаттера из справочника."""
    chatter = await db.get(CatalogChatter, chatter_id)
    if not chatter or chatter.tenant_id != owner.tenant_id:
        raise HTTPException(status_code=404, detail="Чаттер не найден")

    # Проверить что у чаттера уже нет активного аккаунта
    existing = await db.execute(
        select(User).where(
            and_(User.chatter_id == chatter_id, User.active.is_(True))
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="У этого чаттера уже есть аккаунт")

    # Если есть неиспользованный активный инвайт — вернуть его
    active_invite = await db.execute(
        select(ChatterInvite).where(
            and_(
                ChatterInvite.chatter_id == chatter_id,
                ChatterInvite.tenant_id == owner.tenant_id,
                ChatterInvite.used.is_(False),
                ChatterInvite.expires_at > datetime.utcnow(),
            )
        )
    )
    invite = active_invite.scalar_one_or_none()
    if invite is None:
        invite = ChatterInvite(
            tenant_id=owner.tenant_id,
            chatter_id=chatter_id,
            token=secrets.token_urlsafe(32),
            expires_at=datetime.utcnow() + timedelta(days=7),
            created_by_user_id=owner.id,
        )
        db.add(invite)
        await db.commit()
        await db.refresh(invite)

    frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
    invite_url = f"{frontend_url}/join/{invite.token}"

    return {
        "invite_id": invite.id,
        "token": invite.token,
        "url": invite_url,
        "expires_at": invite.expires_at.isoformat(),
        "chatter_name": chatter.name,
    }


@router.get("/chatter")
async def list_chatter_invites(
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Список всех инвайтов текущего owner (активные и использованные)."""
    from sqlalchemy import text

    result = await db.execute(
        text(
            """SELECT i.id, i.token, i.used, i.expires_at, i.created_at,
                      c.name AS chatter_name
               FROM chatter_invites i
               JOIN chatters c ON i.chatter_id = c.id
               WHERE i.tenant_id = :tid
               ORDER BY i.created_at DESC"""
        ),
        {"tid": owner.tenant_id},
    )
    return {"items": [dict(r) for r in result.mappings()]}


@router.delete("/chatter/{invite_id}")
async def revoke_invite(
    invite_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Отозвать инвайт."""
    invite = await db.get(ChatterInvite, invite_id)
    if not invite or invite.tenant_id != owner.tenant_id:
        raise HTTPException(status_code=404, detail="Инвайт не найден")
    await db.delete(invite)
    await db.commit()
    return {"success": True}


# ─── Публичные эндпоинты (без авторизации) ───────────────────────────────────


@router.get("/info/{token}")
async def get_invite_info(token: str, db: AsyncSession = Depends(get_db)):
    """Информация об инвайте перед регистрацией (публичный)."""
    from sqlalchemy import text

    result = await db.execute(
        text(
            """SELECT i.id, i.used, i.expires_at,
                      c.name AS chatter_name,
                      t.agency_name
               FROM chatter_invites i
               JOIN chatters c ON i.chatter_id = c.id
               JOIN tenants t ON i.tenant_id = t.id
               WHERE i.token = :token"""
        ),
        {"token": token},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Инвайт не найден")
    if row["used"]:
        raise HTTPException(status_code=400, detail="Инвайт уже использован")
    if row["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Срок действия инвайта истёк")

    return {
        "chatter_name": row["chatter_name"],
        "agency_name": row["agency_name"],
    }


class AcceptInviteRequest(BaseModel):
    token: str
    email: str
    password: str
    full_name: str


@router.post("/accept")
async def accept_invite(
    data: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Чаттер принимает инвайт и создаёт свой аккаунт."""
    from sqlalchemy import text

    # Найти инвайт
    result = await db.execute(
        text("SELECT * FROM chatter_invites WHERE token = :token"),
        {"token": data.token},
    )
    invite_row = result.mappings().first()
    if not invite_row:
        raise HTTPException(status_code=400, detail="Инвайт не найден")
    if invite_row["used"]:
        raise HTTPException(status_code=400, detail="Инвайт уже использован")
    if invite_row["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Срок действия инвайта истёк")

    # Проверить email на уникальность
    email = data.email.lower().strip()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    # Создать пользователя с ролью chatter
    user = User(
        tenant_id=invite_row["tenant_id"],
        email=email,
        hashed_password=hash_password(data.password),
        role="chatter",
        full_name=data.full_name.strip(),
        chatter_id=invite_row["chatter_id"],
        active=True,
    )
    db.add(user)
    await db.flush()

    # Пометить инвайт использованным
    await db.execute(
        text("UPDATE chatter_invites SET used = TRUE, used_at = NOW() WHERE id = :iid"),
        {"iid": invite_row["id"]},
    )
    await db.commit()
    await db.refresh(user)

    token = create_access_token(
        tenant_id=user.tenant_id,
        email=user.email,
        user_id=user.id,
        role="chatter",
    )
    return {"access_token": token, "token_type": "bearer", "role": "chatter"}
