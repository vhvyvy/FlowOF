"""Manual curl-style checks for admins-review P.1 (owner token required)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-local")
os.environ.setdefault("FILE_STORAGE_ROOT", "./local_storage")

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from auth import create_access_token
from database import _asyncpg_connect_args
from models import User

_db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://neondb_owner:npg_yDrCmcTs50xv@"
    "ep-broad-forest-alh2ugau-pooler.c-3.eu-central-1.aws.neon.tech/neondb",
)
if "?sslmode=" in _db_url:
    _db_url = _db_url.split("?sslmode=")[0]
_engine = create_async_engine(
    _db_url, connect_args={**_asyncpg_connect_args(_db_url), "timeout": 120}
)
Session = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
PREFIX = "/api/v1/dashboard/admins-review"


async def _owner_token(tenant_id: int = 1) -> tuple[str, int]:
    async with Session() as db:
        owner = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.role == "owner",
                    User.active == True,  # noqa: E712
                ).limit(1)
            )
        ).scalar_one()
        admin_id = (
            await db.execute(
                text(
                    "SELECT admin_id FROM admin_cases WHERE tenant_id = :t "
                    "GROUP BY admin_id ORDER BY COUNT(*) DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
        tok = create_access_token(
            tenant_id=owner.tenant_id,
            email=owner.email,
            user_id=owner.id,
            role=owner.role,
        )
        return tok, int(admin_id)


async def _case_ids(tenant_id: int = 1) -> tuple[int | None, int | None]:
    async with Session() as db:
        q = (
            await db.execute(
                text(
                    "SELECT id FROM admin_cases WHERE tenant_id = :t "
                    "AND case_type = 'quantitative' ORDER BY id DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).scalar_one_or_none()
        qual = (
            await db.execute(
                text(
                    "SELECT id FROM admin_cases WHERE tenant_id = :t "
                    "AND case_type = 'qualitative' ORDER BY id DESC LIMIT 1"
                ),
                {"t": tenant_id},
            )
        ).scalar_one_or_none()
        return q, qual


async def main() -> None:
    token, admin_id = await _owner_token(1)
    headers = {"Authorization": f"Bearer {token}"}
    quant_id, qual_id = await _case_ids(1)

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        print("=== a) GET /admins/{id}/cases?include_closed=true ===")
        r = await client.get(
            f"{PREFIX}/admins/{admin_id}/cases",
            params={"include_closed": True},
            headers=headers,
        )
        print(r.status_code)
        data = r.json()
        print(json.dumps(data[:3] if isinstance(data, list) else data, ensure_ascii=False, indent=2, default=str))
        if isinstance(data, list) and data:
            types = {row.get("case_type") for row in data}
            print("case_types seen:", types)
            print("sample chatter_display_name:", data[0].get("chatter_display_name"))

        if quant_id:
            print(f"\n=== b) GET /cases/{quant_id} (quantitative) ===")
            r = await client.get(f"{PREFIX}/cases/{quant_id}", headers=headers)
            print(r.status_code)
            print(json.dumps(r.json(), ensure_ascii=False, indent=2, default=str)[:2000])

        if qual_id:
            print(f"\n=== c) GET /cases/{qual_id} (qualitative) ===")
            r = await client.get(f"{PREFIX}/cases/{qual_id}", headers=headers)
            print(r.status_code)
            print(json.dumps(r.json(), ensure_ascii=False, indent=2, default=str)[:2000])

        print("\n=== d) POST /recalc-snapshots (all admins) ===")
        r = await client.post(f"{PREFIX}/recalc-snapshots", headers=headers)
        print(r.status_code)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2, default=str))

        print("\n=== e) POST /recalc-snapshots?admin_id=53 ===")
        r = await client.post(
            f"{PREFIX}/recalc-snapshots",
            params={"admin_id": 53},
            headers=headers,
        )
        print(r.status_code)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2, default=str))

    print("\n=== f) nightly_recalc_all_tenant_snapshots (manual cron) ===")
    from services.admin_kpi_calc import nightly_recalc_all_tenant_snapshots

    stats = await nightly_recalc_all_tenant_snapshots()
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))

    await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
