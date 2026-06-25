"""Библиотека скриптов чаттера — папки и скрипты."""
from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_chatter
from models import User

router = APIRouter(prefix="/api/v1/me/scripts", tags=["scripts"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class FolderCreate(BaseModel):
    name: str

class FolderUpdate(BaseModel):
    name: str

class ScriptCreate(BaseModel):
    folder_id: Optional[int] = None
    title: str
    content: str
    tags: Optional[str] = None

class ScriptUpdate(BaseModel):
    folder_id: Optional[int] = None
    title: str
    content: str
    tags: Optional[str] = None


# ─── Folders ─────────────────────────────────────────────────────────────────

@router.get("/folders")
async def list_folders(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            """SELECT f.id, f.name, f.sort_order,
                      COUNT(s.id) AS script_count
               FROM script_folders f
               LEFT JOIN scripts s ON s.folder_id = f.id AND s.user_id = f.user_id
               WHERE f.user_id = :uid
               GROUP BY f.id
               ORDER BY f.sort_order ASC, f.id ASC"""
        ),
        {"uid": user.id},
    )
    return {"folders": [dict(r) for r in result.mappings()]}


@router.post("/folders", status_code=201)
async def create_folder(
    data: FolderCreate,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            "INSERT INTO script_folders (user_id, name) VALUES (:uid, :name) RETURNING id"
        ),
        {"uid": user.id, "name": data.name.strip()},
    )
    new_id = result.scalar()
    await db.commit()
    return {"id": new_id, "success": True}


@router.put("/folders/{folder_id}")
async def rename_folder(
    folder_id: int,
    data: FolderUpdate,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        text("SELECT id FROM script_folders WHERE id = :id AND user_id = :uid"),
        {"id": folder_id, "uid": user.id},
    )
    if not r.mappings().first():
        raise HTTPException(status_code=404, detail="Папка не найдена")
    await db.execute(
        text("UPDATE script_folders SET name = :name WHERE id = :id"),
        {"name": data.name.strip(), "id": folder_id},
    )
    await db.commit()
    return {"success": True}


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        text("SELECT id FROM script_folders WHERE id = :id AND user_id = :uid"),
        {"id": folder_id, "uid": user.id},
    )
    if not r.mappings().first():
        raise HTTPException(status_code=404, detail="Папка не найдена")
    # Detach scripts — do not delete them
    await db.execute(
        text("UPDATE scripts SET folder_id = NULL WHERE folder_id = :fid AND user_id = :uid"),
        {"fid": folder_id, "uid": user.id},
    )
    await db.execute(
        text("DELETE FROM script_folders WHERE id = :id"),
        {"id": folder_id},
    )
    await db.commit()
    return {"success": True}


# ─── Scripts ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_scripts(
    folder_id: Optional[int] = Query(None, description="null=all, 0=no folder"),
    search: Optional[str] = Query(None),
    sort: str = Query("date", regex="^(date|popular)$"),
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    where = ["s.user_id = :uid"]
    params: dict = {"uid": user.id}

    if folder_id == 0:
        where.append("s.folder_id IS NULL")
    elif folder_id is not None:
        where.append("s.folder_id = :fid")
        params["fid"] = folder_id

    if search:
        where.append("(s.title ILIKE :q OR s.content ILIKE :q OR s.tags ILIKE :q)")
        params["q"] = f"%{search}%"

    order = "s.created_at DESC" if sort == "date" else "s.copy_count DESC"
    sql = f"""
        SELECT s.id, s.folder_id, s.title, s.content, s.tags,
               s.copy_count, s.created_at, s.updated_at,
               f.name AS folder_name
        FROM scripts s
        LEFT JOIN script_folders f ON f.id = s.folder_id
        WHERE {' AND '.join(where)}
        ORDER BY {order}
    """
    result = await db.execute(text(sql), params)
    items = []
    for r in result.mappings():
        row = dict(r)
        row["created_at"] = str(row["created_at"]) if row.get("created_at") else None
        row["updated_at"] = str(row["updated_at"]) if row.get("updated_at") else None
        items.append(row)
    return {"scripts": items}


@router.post("", status_code=201)
async def create_script(
    data: ScriptCreate,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    if data.folder_id:
        fr = await db.execute(
            text("SELECT id FROM script_folders WHERE id = :id AND user_id = :uid"),
            {"id": data.folder_id, "uid": user.id},
        )
        if not fr.mappings().first():
            raise HTTPException(status_code=404, detail="Папка не найдена")
    result = await db.execute(
        text(
            """INSERT INTO scripts (user_id, folder_id, title, content, tags)
               VALUES (:uid, :fid, :title, :content, :tags)
               RETURNING id"""
        ),
        {"uid": user.id, "fid": data.folder_id, "title": data.title,
         "content": data.content, "tags": data.tags},
    )
    new_id = result.scalar()
    await db.commit()
    return {"id": new_id, "success": True}


@router.put("/{script_id}")
async def update_script(
    script_id: int,
    data: ScriptUpdate,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        text("SELECT id FROM scripts WHERE id = :id AND user_id = :uid"),
        {"id": script_id, "uid": user.id},
    )
    if not r.mappings().first():
        raise HTTPException(status_code=404, detail="Скрипт не найден")
    await db.execute(
        text(
            """UPDATE scripts SET folder_id=:fid, title=:title, content=:content,
               tags=:tags, updated_at=NOW() WHERE id=:id"""
        ),
        {"fid": data.folder_id, "title": data.title,
         "content": data.content, "tags": data.tags, "id": script_id},
    )
    await db.commit()
    return {"success": True}


@router.delete("/{script_id}")
async def delete_script(
    script_id: int,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        text("SELECT id FROM scripts WHERE id = :id AND user_id = :uid"),
        {"id": script_id, "uid": user.id},
    )
    if not r.mappings().first():
        raise HTTPException(status_code=404, detail="Скрипт не найден")
    await db.execute(text("DELETE FROM scripts WHERE id = :id"), {"id": script_id})
    await db.commit()
    return {"success": True}


@router.post("/{script_id}/copy")
async def increment_copy(
    script_id: int,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("UPDATE scripts SET copy_count = copy_count + 1 WHERE id = :id AND user_id = :uid"),
        {"id": script_id, "uid": user.id},
    )
    await db.commit()
    return {"success": True}
